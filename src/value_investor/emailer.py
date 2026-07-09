"""Email delivery for screening reports."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from value_investor.backtest import BacktestSummary, format_backtest_text
from value_investor.deep_analysis import DeepAnalysis
from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.format import format_research_html, format_research_text
from value_investor.run_diff import RunDiff, format_run_diff_text
from value_investor.simulator import SimulationSummary, format_simulation_text
from value_investor.summary import CompanyReport
from value_investor.technical_analysis import timing_label


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_to: str
    email_from: str | None = None
    use_tls: bool = True

    @classmethod
    def from_env(cls) -> EmailConfig:
        host = os.environ.get("SMTP_HOST")
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")
        email_to = os.environ.get("EMAIL_TO")

        missing = [k for k, v in [
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
            ("EMAIL_TO", email_to),
        ] if not v]
        if missing:
            raise ValueError(f"Missing required email env vars: {', '.join(missing)}")

        return cls(
            smtp_host=host,
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=user,
            smtp_password=password,
            email_to=email_to,
            email_from=os.environ.get("EMAIL_FROM", user),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        )


SIGNAL_COLORS = {
    "strong_buy": "#1b7f3a",
    "buy": "#2e9c4f",
    "hold": "#b8860b",
    "avoid": "#b33a3a",
    "insufficient_data": "#666666",
}

TIMING_COLORS = {
    "accumulate": "#1b7f3a",
    "neutral": "#b8860b",
    "wait": "#b33a3a",
    "insufficient_data": "#666666",
}

VERDICT_COLORS = {
    "accumulate": "#1b7f3a",
    "neutral": "#b8860b",
    "caution": "#c45c00",
    "pass": "#b33a3a",
}


def _research_overlay_label(report: CompanyReport) -> str | None:
    if not report.research_verdict:
        return None
    label = report.research_verdict.replace("_", " ").title()
    if report.adjusted_signal and report.adjusted_signal != report.signal:
        adj = report.adjusted_signal.replace("_", " ").title()
        return f"Research: {label} → {adj}"
    return f"Research: {label}"


def _favorable_timing_picks(reports: list[CompanyReport]) -> list[CompanyReport]:
    return [
        r
        for r in reports
        if r.signal in ("strong_buy", "buy")
        and r.timing_signal == "accumulate"
    ]


def _strong_buy_trade_plans(reports: list[CompanyReport]) -> list[CompanyReport]:
    return [
        r
        for r in reports
        if r.signal == "strong_buy" and r.trade_plan is not None
    ]


def _format_trade_plans_text(reports: list[CompanyReport]) -> str | None:
    plans = _strong_buy_trade_plans(reports)
    if not plans:
        return None
    lines = [
        "Suggested orders for strong buys (core holding + tactical dip entries):",
    ]
    for report in plans:
        lines.append(f"  • {report.name} ({report.ticker})")
        if report.trade_plan and report.trade_plan.trade_plan_summary:
            lines.append(f"    {report.trade_plan.trade_plan_summary}")
    return "\n".join(lines)


def _format_trade_plans_html(reports: list[CompanyReport]) -> str:
    plans = _strong_buy_trade_plans(reports)
    if not plans:
        return ""
    rows = []
    for report in plans:
        plan = report.trade_plan
        if plan is None:
            continue
        core_text = (
            f"{plan.core_order or 'n/a'}"
            + (f" @ £{plan.core_limit:.2f}" if plan.core_limit is not None else " @ market")
            + (f" ({plan.core_allocation_pct:.0%})" if plan.core_allocation_pct is not None else "")
        )
        tactical_text = (
            f"{plan.tactical_order or 'limit'}"
            + (f" @ £{plan.tactical_limit:.2f}" if plan.tactical_limit is not None else "")
            + (
                f" ({plan.tactical_allocation_pct:.0%})"
                if plan.tactical_allocation_pct is not None
                else ""
            )
        )
        risk_text = ""
        if plan.tactical_stop_loss is not None and plan.tactical_take_profit is not None:
            risk_text = (
                f"Tactical stop £{plan.tactical_stop_loss:.2f}, "
                f"target £{plan.tactical_take_profit:.2f}"
            )
        rows.append(
            f"""
            <tr>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                <strong>{report.name}</strong><br>
                <span style="color:#666">{report.ticker}</span>
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                Core: {core_text}<br>
                Tactical: {tactical_text}
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">{risk_text}</td>
            </tr>
            """
        )
    return f"""
  <div style="background:#f0f4ff;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #2b6cb0">
    <h3 style="margin-top:0">Strong buy trade plans</h3>
    <p style="color:#666;font-size:13px;margin-top:0">
      Core leg builds the long-term holding; tactical limits target short-term dips.
    </p>
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <thead>
        <tr style="background:#e8eef8">
          <th style="padding:10px;text-align:left">Company</th>
          <th style="padding:10px;text-align:left">Orders</th>
          <th style="padding:10px;text-align:left">Tactical risk</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
"""


def _format_favorable_timing_text(reports: list[CompanyReport]) -> str | None:
    picks = _favorable_timing_picks(reports)
    if not picks:
        return None
    lines = ["Value + favourable technical timing:"]
    for report in picks[:10]:
        lines.append(f"  • {report.name} ({report.ticker}) — {report.action_note}")
    if len(picks) > 10:
        lines.append(f"  …and {len(picks) - 10} more")
    return "\n".join(lines)


def format_text_report(
    *,
    run_at: str,
    reports: list[CompanyReport],
    run_diff: RunDiff | None = None,
    deep_analysis: DeepAnalysis | None = None,
    backtest: BacktestSummary | None = None,
    simulation: SimulationSummary | None = None,
    research_summary: ResearchSummary | None = None,
    research_documents: list[ResearchDocument] | None = None,
) -> str:
    lines = [
        f"FTSE 100 Value Screen — {run_at}",
        "=" * 60,
        "",
    ]

    if deep_analysis is not None:
        lines.extend(["DEEP ANALYSIS", "-" * 40, deep_analysis.full_text, ""])

    if backtest is not None:
        lines.extend(["SIGNAL BACKTEST", "-" * 40, format_backtest_text(backtest), ""])

    if simulation is not None:
        lines.extend(["PORTFOLIO SIMULATION", "-" * 40, format_simulation_text(simulation), ""])

    if run_diff is not None:
        lines.extend(["WEEK-OVER-WEEK CHANGES", "-" * 40, format_run_diff_text(run_diff), ""])

    favorable = _format_favorable_timing_text(reports)
    if favorable:
        lines.extend(["MARKET TIMING", "-" * 40, favorable, ""])

    trade_plans = _format_trade_plans_text(reports)
    if trade_plans:
        lines.extend(["STRONG BUY TRADE PLANS", "-" * 40, trade_plans, ""])

    research_text = format_research_text(research_summary, research_documents or [])
    if research_text:
        lines.extend(["STRONG BUY RESEARCH", "-" * 40, research_text, ""])

    counts: dict[str, int] = {}
    for report in reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1

    lines.append(
        "Summary: "
        + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    )
    lines.append("")

    for report in reports:
        label = report.signal.replace("_", " ").title()
        overlay = _research_overlay_label(report)
        lines.append(f"{report.name} ({report.ticker}) — {label}")
        if overlay:
            lines.append(overlay)
        lines.append(report.summary)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def format_html_report(
    *,
    run_at: str,
    reports: list[CompanyReport],
    run_diff: RunDiff | None = None,
    deep_analysis: DeepAnalysis | None = None,
    backtest: BacktestSummary | None = None,
    simulation: SimulationSummary | None = None,
    research_summary: ResearchSummary | None = None,
    research_documents: list[ResearchDocument] | None = None,
) -> str:
    counts: dict[str, int] = {}
    for report in reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1

    summary_bits = "".join(
        f'<span style="margin-right:12px"><strong>{k.replace("_", " ").title()}</strong>: {v}</span>'
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    )

    rows = []
    for report in reports:
        color = SIGNAL_COLORS.get(report.signal, "#333")
        label = report.signal.replace("_", " ").title()
        sector = f' <span style="color:#666">({report.sector})</span>' if report.sector else ""
        timing_color = TIMING_COLORS.get(report.timing_signal, "#666")
        timing_label_text = timing_label(report.timing_signal)
        rsi_html = f"RSI {report.rsi_14:.0f}" if report.rsi_14 is not None else "RSI n/a"
        action_html = (
            f"<br><span style='color:#666;font-size:12px'>{report.action_note}</span>"
            if report.action_note
            else ""
        )
        overlay = _research_overlay_label(report)
        overlay_html = (
            f"<br><span style='color:#666;font-size:12px'>{overlay}</span>"
            if overlay
            else ""
        )
        rows.append(
            f"""
            <tr>
              <td style="padding:12px;border-bottom:1px solid #eee;vertical-align:top">
                <strong>{report.name}</strong><br>
                <span style="color:#666">{report.ticker}</span>{sector}
              </td>
              <td style="padding:12px;border-bottom:1px solid #eee;vertical-align:top">
                <span style="color:{color};font-weight:bold">{label}</span>{overlay_html}<br>
                <span style="color:#666;font-size:12px">{report.models_passed}/{report.model_count} models<br>
                {report.families_passed}/4 families<br>
                Conviction {report.conviction_score:.0%} ({report.stability_label})</span>
              </td>
              <td style="padding:12px;border-bottom:1px solid #eee;vertical-align:top">
                <span style="color:{timing_color};font-weight:bold">{timing_label_text}</span><br>
                <span style="color:#666;font-size:12px">{rsi_html}</span>{action_html}
              </td>
              <td style="padding:12px;border-bottom:1px solid #eee">{report.summary}</td>
            </tr>
            """
        )

    deep_section = ""
    if deep_analysis is not None:
        intro = deep_analysis.executive_intro.replace("\n", "<br>")
        picks = deep_analysis.top_picks_analysis.replace("\n", "<br>")
        flags = deep_analysis.red_flags.replace("\n", "<br>")
        deep_section = f"""
  <div style="background:#f8f9fa;padding:16px;border-radius:8px;margin:16px 0">
    <h3 style="margin-top:0">Deep Analysis</h3>
    <p><strong>Executive intro</strong><br>{intro}</p>
    <p><strong>Top picks</strong><br>{picks}</p>
    <p><strong>Red flags</strong><br>{flags}</p>
  </div>
"""

    backtest_section = ""
    if backtest is not None:
        backtest_text = format_backtest_text(backtest).replace("\n", "<br>")
        backtest_section = f"""
  <div style="background:#eef6ff;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #2b6cb0">
    <h3 style="margin-top:0">Signal backtest</h3>
    <p style="margin-bottom:0">{backtest_text}</p>
  </div>
"""

    simulation_section = ""
    if simulation is not None:
        sim_text = format_simulation_text(simulation).replace("\n", "<br>")
        simulation_section = f"""
  <div style="background:#f3eef9;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #6b46c1">
    <h3 style="margin-top:0">Portfolio simulation</h3>
    <p style="margin-bottom:0">{sim_text}</p>
  </div>
"""

    diff_section = ""
    if run_diff is not None:
        diff_text = format_run_diff_text(run_diff).replace("\n", "<br>")
        diff_section = f"""
  <div style="background:#fff8e6;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #b8860b">
    <h3 style="margin-top:0">Week-over-week changes</h3>
    <p style="margin-bottom:0">{diff_text}</p>
  </div>
"""

    timing_section = ""
    favorable_text = _format_favorable_timing_text(reports)
    if favorable_text:
        timing_html = favorable_text.replace("\n", "<br>")
        timing_section = f"""
  <div style="background:#eefaf0;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #1b7f3a">
    <h3 style="margin-top:0">Market timing</h3>
    <p style="margin-bottom:0">{timing_html}</p>
  </div>
"""

    trade_plans_section = _format_trade_plans_html(reports)
    research_section = format_research_html(research_documents or [], research_summary)

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:0 auto">
  <h2>FTSE 100 Value Screen</h2>
  <p style="color:#666">{run_at}</p>
  {deep_section}
  {backtest_section}
  {simulation_section}
  {timing_section}
  {trade_plans_section}
  {research_section}
  {diff_section}
  <p>{summary_bits}</p>
  <table style="width:100%;border-collapse:collapse;margin-top:16px">
    <thead>
      <tr style="background:#f5f5f5">
        <th style="padding:12px;text-align:left">Company</th>
        <th style="padding:12px;text-align:left">Value signal</th>
        <th style="padding:12px;text-align:left">Timing</th>
        <th style="padding:12px;text-align:left">Summary</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <p style="color:#888;font-size:12px;margin-top:24px">
    Research signals only — not investment advice. Verify figures before acting.
  </p>
</body>
</html>"""


def send_report_email(
    *,
    subject: str,
    text_body: str,
    html_body: str,
    config: EmailConfig,
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.email_from or config.smtp_user
    message["To"] = config.email_to
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=60) as server:
        if config.use_tls:
            server.starttls()
        server.login(config.smtp_user, config.smtp_password)
        server.sendmail(message["From"], [config.email_to], message.as_string())
