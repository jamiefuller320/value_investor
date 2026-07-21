"""Email delivery for screening reports."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from value_investor.backtest import BacktestSummary, format_backtest_text
from value_investor.decision_pack import (
    build_decision_packs,
    format_decision_packs_html,
    format_decision_packs_text,
)
from value_investor.deep_analysis import DeepAnalysis
from value_investor.historical_analysis import (
    HistoricalAnalysisSummary,
    format_historical_analysis_html,
    format_historical_analysis_text,
)
from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.format import (
    format_gap_fill_html,
    format_gap_fill_text,
    format_research_html,
    format_research_text,
)
from value_investor.run_diff import RunDiff, format_run_diff_text
from value_investor.simulator import SimulationComparison, format_simulation_comparison_text
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


def _buy_tier_trade_plans(reports: list[CompanyReport]) -> list[CompanyReport]:
    return [
        r
        for r in reports
        if r.signal in ("strong_buy", "buy") and r.trade_plan is not None
    ]


def _format_trade_plans_text(reports: list[CompanyReport]) -> str | None:
    plans = _buy_tier_trade_plans(reports)
    if not plans:
        return None
    lines = [
        "Suggested orders for buy-tier names (core holding + tactical dip entries):",
    ]
    for report in plans:
        lines.append(
            f"  • {report.name} ({report.ticker}) — {report.signal.replace('_', ' ')}"
        )
        if report.trade_plan and report.trade_plan.trade_plan_summary:
            lines.append(f"    {report.trade_plan.trade_plan_summary}")
    return "\n".join(lines)


def _format_trade_plans_html(reports: list[CompanyReport]) -> str:
    plans = _buy_tier_trade_plans(reports)
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
                <span style="color:#666">{report.ticker} · {report.signal.replace('_', ' ')}</span>
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
    <h3 style="margin-top:0">Buy-tier trade plans</h3>
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


def _universe_coverage_note(
    *,
    excluded_investment_vehicles: int,
    insufficient_data_count: int,
    trust_report_count: int = 0,
) -> str | None:
    bits: list[str] = []
    if trust_report_count > 0:
        bits.append(
            f"Screened {trust_report_count} investment trusts/funds on the separate "
            "discount/income track (book value as NAV proxy)"
        )
    elif excluded_investment_vehicles > 0:
        bits.append(
            f"Excluded {excluded_investment_vehicles} investment trusts/funds "
            "(operating-company metrics not applicable)"
        )
    if insufficient_data_count > 0:
        bits.append(
            f"{insufficient_data_count} operating-company name(s) marked insufficient data "
            "(true fetch/fundamental gaps)"
        )
    if not bits:
        return None
    return ". ".join(bits) + "."


def _format_trust_section_text(trust_reports: list[CompanyReport]) -> str | None:
    if not trust_reports:
        return None
    counts: dict[str, int] = {}
    for report in trust_reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1
    lines = [
        "INVESTMENT TRUST TRACK",
        "-" * 40,
        "Summary: "
        + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])),
        "Models use discount to book/NAV proxy, distribution yield, and premium risk.",
        "",
    ]
    # Lead with buy-tier trusts, then the rest (cap detail length).
    ordered = sorted(
        trust_reports,
        key=lambda r: ({"strong_buy": 0, "buy": 1, "hold": 2, "avoid": 3}.get(r.signal, 4), -r.conviction_score),
    )
    for report in ordered[:25]:
        label = report.signal.replace("_", " ").title()
        lines.append(f"{report.name} ({report.ticker}) — {label}")
        lines.append(report.summary)
        lines.append("")
    if len(ordered) > 25:
        lines.append(f"…and {len(ordered) - 25} more trusts in latest_trust_signals.csv")
        lines.append("")
    return "\n".join(lines)


def _format_trust_section_html(trust_reports: list[CompanyReport]) -> str:
    if not trust_reports:
        return ""
    counts: dict[str, int] = {}
    for report in trust_reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1
    summary_bits = "".join(
        f'<span style="margin-right:12px"><strong>{k.replace("_", " ").title()}</strong>: {v}</span>'
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    )
    ordered = sorted(
        trust_reports,
        key=lambda r: ({"strong_buy": 0, "buy": 1, "hold": 2, "avoid": 3}.get(r.signal, 4), -r.conviction_score),
    )
    rows = []
    for report in ordered[:25]:
        color = SIGNAL_COLORS.get(report.signal, "#333")
        label = report.signal.replace("_", " ").title()
        metrics = ""
        if report.key_metrics:
            metrics = " · ".join(f"{k} {v}" for k, v in list(report.key_metrics.items())[:4])
        rows.append(
            f"""
            <tr>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                <strong>{report.name}</strong><br>
                <span style="color:#666">{report.ticker}</span>
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee;vertical-align:top">
                <span style="color:{color};font-weight:bold">{label}</span><br>
                <span style="color:#666;font-size:12px">{report.models_passed}/{report.model_count} models</span>
              </td>
              <td style="padding:10px;border-bottom:1px solid #eee;font-size:13px">
                {metrics}<br>{report.summary}
              </td>
            </tr>
            """
        )
    more = ""
    if len(ordered) > 25:
        more = f'<p style="color:#666;font-size:12px">…and {len(ordered) - 25} more trusts.</p>'
    return f"""
  <div style="background:#f7fafc;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #2b6cb0">
    <h3 style="margin-top:0">Investment trust track</h3>
    <p style="color:#555;font-size:13px;margin-top:0">
      Separate screen for closed-end funds / trusts using discount to book (NAV proxy),
      yield, and premium risk — not the operating-company Graham models.
    </p>
    <p>{summary_bits}</p>
    <table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>
    {more}
  </div>
"""


def format_text_report(
    *,
    run_at: str,
    reports: list[CompanyReport],
    run_diff: RunDiff | None = None,
    deep_analysis: DeepAnalysis | None = None,
    backtest: BacktestSummary | None = None,
    simulation: SimulationComparison | None = None,
    historical_analysis: HistoricalAnalysisSummary | None = None,
    research_summary: ResearchSummary | None = None,
    research_documents: list[ResearchDocument] | None = None,
    gap_fill_summary=None,
    screen_label: str = "FTSE 350",
    excluded_investment_vehicles: int = 0,
    trust_reports: list[CompanyReport] | None = None,
) -> str:
    lines = [
        f"{screen_label} Value Screen — {run_at}",
        "=" * 60,
        "",
    ]

    if deep_analysis is not None:
        lines.extend(["DEEP ANALYSIS", "-" * 40, deep_analysis.full_text, ""])

    if backtest is not None:
        lines.extend(["SIGNAL BACKTEST", "-" * 40, format_backtest_text(backtest), ""])

    if simulation is not None:
        lines.extend([
            "PORTFOLIO SIMULATION",
            "-" * 40,
            format_simulation_comparison_text(simulation),
            "",
        ])

    if historical_analysis is not None and historical_analysis.has_results():
        lines.extend([
            "HISTORICAL ANALYSIS",
            "-" * 40,
            format_historical_analysis_text(historical_analysis),
            "",
        ])

    if run_diff is not None:
        lines.extend(["WEEK-OVER-WEEK CHANGES", "-" * 40, format_run_diff_text(run_diff), ""])

    favorable = _format_favorable_timing_text(reports)
    if favorable:
        lines.extend(["MARKET TIMING", "-" * 40, favorable, ""])

    trade_plans = _format_trade_plans_text(reports)
    if trade_plans:
        lines.extend(["BUY-TIER TRADE PLANS", "-" * 40, trade_plans, ""])

    packs = build_decision_packs(reports, research_documents)
    packs.sort(
        key=lambda p: ({"strong_buy": 0, "buy": 1}.get(p.signal, 9), -(p.conviction_score or 0))
    )
    packs_text = format_decision_packs_text(packs)
    if packs_text:
        lines.extend(["VERIFY-BEFORE-TRADE PACKS", "-" * 40, packs_text, ""])

    research_text = format_research_text(research_summary, research_documents or [])
    if research_text:
        lines.extend(["STRONG BUY RESEARCH", "-" * 40, research_text, ""])

    gap_text = format_gap_fill_text(gap_fill_summary)
    if gap_text:
        lines.extend(["RED-FLAG RESEARCH LOOP", "-" * 40, gap_text, ""])

    counts: dict[str, int] = {}
    for report in reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1

    lines.append(
        "Summary: "
        + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    )
    trust_reports = trust_reports or []
    coverage = _universe_coverage_note(
        excluded_investment_vehicles=excluded_investment_vehicles,
        insufficient_data_count=counts.get("insufficient_data", 0),
        trust_report_count=len(trust_reports),
    )
    if coverage:
        lines.append(coverage)
    lines.append("")

    trust_section = _format_trust_section_text(trust_reports)
    if trust_section:
        lines.extend([trust_section, ""])

    lines.extend(["OPERATING COMPANIES", "-" * 40, ""])
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
    simulation: SimulationComparison | None = None,
    historical_analysis: HistoricalAnalysisSummary | None = None,
    research_summary: ResearchSummary | None = None,
    research_documents: list[ResearchDocument] | None = None,
    gap_fill_summary=None,
    screen_label: str = "FTSE 350",
    excluded_investment_vehicles: int = 0,
    trust_reports: list[CompanyReport] | None = None,
) -> str:
    counts: dict[str, int] = {}
    for report in reports:
        counts[report.signal] = counts.get(report.signal, 0) + 1

    summary_bits = "".join(
        f'<span style="margin-right:12px"><strong>{k.replace("_", " ").title()}</strong>: {v}</span>'
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    )
    trust_reports = trust_reports or []
    coverage = _universe_coverage_note(
        excluded_investment_vehicles=excluded_investment_vehicles,
        insufficient_data_count=counts.get("insufficient_data", 0),
        trust_report_count=len(trust_reports),
    )
    coverage_html = (
        f'<p style="color:#666;font-size:13px;margin-top:4px">{coverage}</p>' if coverage else ""
    )
    trust_section = _format_trust_section_html(trust_reports)

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
        sim_text = format_simulation_comparison_text(simulation).replace("\n", "<br>")
        simulation_section = f"""
  <div style="background:#f3eef9;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #6b46c1">
    <h3 style="margin-top:0">Portfolio simulation</h3>
    <p style="margin-bottom:0">{sim_text}</p>
  </div>
"""

    historical_section = format_historical_analysis_html(historical_analysis) if historical_analysis else ""

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
    packs = build_decision_packs(reports, research_documents)
    packs.sort(
        key=lambda p: ({"strong_buy": 0, "buy": 1}.get(p.signal, 9), -(p.conviction_score or 0))
    )
    packs_section = format_decision_packs_html(packs)
    research_section = format_research_html(research_documents or [], research_summary)
    gap_fill_section = format_gap_fill_html(gap_fill_summary)

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:0 auto">
  <h2>{screen_label} Value Screen</h2>
  <p style="color:#666">{run_at}</p>
  {deep_section}
  {backtest_section}
  {simulation_section}
  {historical_section}
  {timing_section}
  {trade_plans_section}
  {packs_section}
  {research_section}
  {gap_fill_section}
  {diff_section}
  <p><strong>Operating companies</strong> — {summary_bits}</p>
  {coverage_html}
  {trust_section}
  <h3>Operating company signals</h3>
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
