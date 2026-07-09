"""Email delivery for screening reports."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from value_investor.backtest import BacktestSummary, format_backtest_text
from value_investor.deep_analysis import DeepAnalysis
from value_investor.run_diff import RunDiff, format_run_diff_text
from value_investor.summary import CompanyReport


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


def format_text_report(
    *,
    run_at: str,
    reports: list[CompanyReport],
    run_diff: RunDiff | None = None,
    deep_analysis: DeepAnalysis | None = None,
    backtest: BacktestSummary | None = None,
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

    if run_diff is not None:
        lines.extend(["WEEK-OVER-WEEK CHANGES", "-" * 40, format_run_diff_text(run_diff), ""])

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
        lines.append(f"{report.name} ({report.ticker}) — {label}")
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
        rows.append(
            f"""
            <tr>
              <td style="padding:12px;border-bottom:1px solid #eee;vertical-align:top">
                <strong>{report.name}</strong><br>
                <span style="color:#666">{report.ticker}</span>{sector}
              </td>
              <td style="padding:12px;border-bottom:1px solid #eee;vertical-align:top">
                <span style="color:{color};font-weight:bold">{label}</span><br>
                <span style="color:#666;font-size:12px">{report.models_passed}/{report.model_count} models<br>
                {report.families_passed}/4 families<br>
                Conviction {report.conviction_score:.0%} ({report.stability_label})</span>
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

    diff_section = ""
    if run_diff is not None:
        diff_text = format_run_diff_text(run_diff).replace("\n", "<br>")
        diff_section = f"""
  <div style="background:#fff8e6;padding:16px;border-radius:8px;margin:16px 0;border-left:4px solid #b8860b">
    <h3 style="margin-top:0">Week-over-week changes</h3>
    <p style="margin-bottom:0">{diff_text}</p>
  </div>
"""

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;color:#222;max-width:900px;margin:0 auto">
  <h2>FTSE 100 Value Screen</h2>
  <p style="color:#666">{run_at}</p>
  {deep_section}
  {backtest_section}
  {diff_section}
  <p>{summary_bits}</p>
  <table style="width:100%;border-collapse:collapse;margin-top:16px">
    <thead>
      <tr style="background:#f5f5f5">
        <th style="padding:12px;text-align:left">Company</th>
        <th style="padding:12px;text-align:left">Signal</th>
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
