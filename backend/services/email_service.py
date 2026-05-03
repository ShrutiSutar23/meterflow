# backend/services/email_service.py
"""
Email Notification Service (Day 11)
======================================
Sends transactional emails using SendGrid.
Transactional = triggered by user actions, not marketing blasts.

Emails we send in MeterFlow:
  1. Welcome email         → after signup
  2. Invite email          → when someone is invited to an org
  3. Invoice email         → monthly invoice generated
  4. Payment failed email  → card declined
  5. Usage warning email   → 80% / 100% of limit reached
  6. Password reset email  → when user requests it

WHY SENDGRID?
  - 100 free emails/day forever
  - Delivery tracking (open rates, bounces)
  - Template engine (HTML emails without coding)
  - Used by Uber, Airbnb, Spotify for transactional email

ALTERNATIVE: AWS SES ($0.10 per 1000 emails — cheapest option)

SETUP STEPS:
  1. Sign up at sendgrid.com (free)
  2. Settings → API Keys → Create API Key (Full Access)
  3. Add to .env: SENDGRID_API_KEY=SG.xxxx...
  4. Verify your sender email in SendGrid dashboard
  5. Add to .env: EMAIL_FROM=noreply@yourdomain.com

Interview topic:
  "Why not just use smtplib/Gmail directly?"
  Answer: Gmail throttles to 500/day. Rate limits, deliverability,
  bounce handling, unsubscribe compliance (CAN-SPAM/GDPR) are all
  solved by a proper ESP (Email Service Provider) like SendGrid.
"""

import asyncio
from typing import Optional
from datetime import datetime

import httpx

from backend.config.settings import settings


# ── Email Templates (inline HTML) ────────────────────────────────────────────
# In production you'd store these in SendGrid's template editor.
# For now we build them in Python — easy to version control.

def _base_template(title: str, body_html: str, cta_url: str = None, cta_text: str = None) -> str:
    """Wraps any email content in a clean, minimal HTML template."""
    cta_block = ""
    if cta_url and cta_text:
        cta_block = f"""
        <div style="text-align:center;margin:32px 0;">
          <a href="{cta_url}"
             style="background:#000;color:#fff;padding:12px 28px;
                    border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">
            {cta_text}
          </a>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e0e0e0;">
        <!-- Header -->
        <tr>
          <td style="background:#000;padding:24px 32px;">
            <span style="color:#00ff88;font-size:20px;font-weight:700;
                         font-family:monospace;letter-spacing:-0.5px;">⚡ MeterFlow</span>
          </td>
        </tr>
        <!-- Title -->
        <tr>
          <td style="padding:32px 32px 0;">
            <h1 style="margin:0;font-size:24px;font-weight:600;color:#111;">{title}</h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:16px 32px 0;font-size:15px;line-height:1.7;color:#444;">
            {body_html}
          </td>
        </tr>
        {cta_block}
        <!-- Footer -->
        <tr>
          <td style="padding:24px 32px;border-top:1px solid #f0f0f0;
                     font-size:12px;color:#999;line-height:1.6;">
            You're receiving this because you have a MeterFlow account.<br>
            MeterFlow · Usage-Based API Billing Platform
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# SENDGRID API CALLER
# ═══════════════════════════════════════════════════════════════════════════════

async def _send_email(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str = None,
) -> bool:
    """
    Send one email via SendGrid REST API.

    We use the REST API directly (not the sendgrid Python library)
    so you understand exactly what's happening — just a POST request.

    SendGrid API reference:
    https://docs.sendgrid.com/api-reference/mail-send/mail-send

    Returns True on success, False on failure (we never raise — email
    failures should never crash the main application flow).
    """
    api_key = getattr(settings, "SENDGRID_API_KEY", "")
    from_addr = from_email or getattr(settings, "EMAIL_FROM", "noreply@meterflow.io")

    if not api_key or api_key.startswith("SG.your"):
        # Not configured — log but don't crash
        print(f"📧 [EMAIL SKIPPED - not configured] To: {to_email} | Subject: {subject}")
        return False

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_addr, "name": "MeterFlow"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            # SendGrid returns 202 Accepted on success
            success = response.status_code == 202
            if not success:
                print(f"SendGrid error {response.status_code}: {response.text}")
            return success
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL EMAIL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def send_welcome_email(email: str, username: str) -> bool:
    """
    Sent immediately after signup.
    Introduces the product and links to docs.
    """
    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>Welcome to MeterFlow! Your account is ready.</p>
    <p>Here's what you can do right now:</p>
    <ul style="padding-left:20px;line-height:2;">
      <li>Generate your first API key</li>
      <li>Make API calls and watch usage tracked in real time</li>
      <li>View your analytics dashboard</li>
    </ul>
    <p>You're on the <strong>Free plan</strong> — 10,000 API calls per month, no credit card needed.</p>
    """
    html = _base_template(
        title=f"Welcome to MeterFlow, {username}!",
        body_html=body,
        cta_url="http://localhost:5173/dashboard",
        cta_text="Open Dashboard →",
    )
    return await _send_email(email, "Welcome to MeterFlow 👋", html)


async def send_org_invite_email(
    to_email: str,
    org_name: str,
    invited_by: str,
    invite_token: str,
    role: str,
) -> bool:
    """
    Sent when a user is invited to join an organization.
    Contains the secure one-time invite link.
    """
    invite_url = f"http://localhost:5173/invites/{invite_token}/accept"
    body = f"""
    <p><strong>{invited_by}</strong> has invited you to join
    <strong>{org_name}</strong> on MeterFlow as a <strong>{role}</strong>.</p>
    <p>Click the button below to accept. This invite expires in 7 days.</p>
    <p style="color:#999;font-size:13px;">If you don't have a MeterFlow account,
    you'll be asked to create one first.</p>
    """
    html = _base_template(
        title=f"You're invited to join {org_name}",
        body_html=body,
        cta_url=invite_url,
        cta_text="Accept Invitation →",
    )
    return await _send_email(
        to_email,
        f"{invited_by} invited you to {org_name} on MeterFlow",
        html,
    )


async def send_invoice_email(
    email: str,
    username: str,
    billing_month: str,
    total_requests: int,
    total_cost_usd: float,
    invoice_id: str,
) -> bool:
    """
    Monthly invoice notification.
    Sent on the 1st of every month after invoice generation.
    """
    cost_str = f"${total_cost_usd:.2f}"
    free_note = " (free plan — no charge)" if total_cost_usd == 0 else ""

    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your MeterFlow invoice for <strong>{billing_month}</strong> is ready.</p>
    <table style="width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;">
      <tr style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:10px 0;color:#666;">Billing period</td>
        <td style="padding:10px 0;text-align:right;font-weight:500;">{billing_month}</td>
      </tr>
      <tr style="border-bottom:1px solid #f0f0f0;">
        <td style="padding:10px 0;color:#666;">Total API calls</td>
        <td style="padding:10px 0;text-align:right;font-weight:500;">{total_requests:,}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;color:#666;font-weight:600;">Amount due</td>
        <td style="padding:10px 0;text-align:right;font-size:20px;font-weight:700;color:#111;">
          {cost_str}{free_note}
        </td>
      </tr>
    </table>
    <p style="font-size:13px;color:#999;">Invoice ID: {invoice_id}</p>
    """
    html = _base_template(
        title=f"Your {billing_month} Invoice",
        body_html=body,
        cta_url="http://localhost:5173/billing",
        cta_text="View Invoice →",
    )
    return await _send_email(email, f"MeterFlow Invoice — {billing_month}", html)


async def send_payment_failed_email(
    email: str,
    username: str,
    amount_usd: float,
    decline_reason: str = "Your card was declined",
) -> bool:
    """
    Sent when Stripe fails to charge the user.
    Urges them to update their payment method before account suspension.
    """
    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>We were unable to process your payment of <strong>${amount_usd:.2f}</strong>.</p>
    <p style="background:#fff3f3;padding:12px 16px;border-radius:6px;
              border-left:3px solid #e53e3e;color:#c53030;">
      {decline_reason}
    </p>
    <p>Please update your payment method to avoid service interruption.
    We'll retry the charge in 3 days.</p>
    <p style="color:#999;font-size:13px;">After 3 failed attempts your account will be
    downgraded to the free plan.</p>
    """
    html = _base_template(
        title="Payment failed — action required",
        body_html=body,
        cta_url="http://localhost:5173/billing",
        cta_text="Update Payment Method →",
    )
    return await _send_email(email, "⚠️ MeterFlow payment failed", html)


async def send_usage_warning_email(
    email: str,
    username: str,
    usage_pct: float,
    requests_used: int,
    requests_limit: int,
    plan: str,
) -> bool:
    """
    Sent at 80% and 100% of monthly request limit.
    Encourages upgrade before hitting the wall.
    """
    is_exceeded = usage_pct >= 100
    title = "You've exceeded your monthly limit" if is_exceeded else f"You've used {usage_pct:.0f}% of your monthly limit"
    color = "#e53e3e" if is_exceeded else "#d69e2e"
    icon = "🚨" if is_exceeded else "⚠️"

    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p style="background:#fffbeb;padding:12px 16px;border-radius:6px;
              border-left:3px solid {color};">
      {icon} You have used <strong>{requests_used:,}</strong> of your
      <strong>{requests_limit:,}</strong> monthly API calls
      (<strong>{usage_pct:.1f}%</strong>).
    </p>
    {"<p><strong>New API calls are now being blocked.</strong> Upgrade your plan to continue.</p>" if is_exceeded else "<p>Upgrade now to avoid interruption at the end of the month.</p>"}
    <p>Current plan: <strong>{plan.title()}</strong></p>
    """
    html = _base_template(
        title=title,
        body_html=body,
        cta_url="http://localhost:5173/billing",
        cta_text="Upgrade Plan →",
    )
    subject = f"{'🚨 API limit exceeded' if is_exceeded else '⚠️ API usage warning'} — MeterFlow"
    return await _send_email(email, subject, html)


async def send_password_reset_email(
    email: str,
    username: str,
    reset_token: str,
) -> bool:
    """
    Sends a password reset link valid for 1 hour.
    Token is stored in Redis with 1hr TTL.
    """
    reset_url = f"http://localhost:5173/reset-password?token={reset_token}"
    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>We received a request to reset your MeterFlow password.</p>
    <p>Click the button below to set a new password. This link expires in <strong>1 hour</strong>.</p>
    <p style="color:#999;font-size:13px;">If you didn't request this, you can safely ignore this email.
    Your password will not change.</p>
    """
    html = _base_template(
        title="Reset your password",
        body_html=body,
        cta_url=reset_url,
        cta_text="Reset Password →",
    )
    return await _send_email(email, "Reset your MeterFlow password", html)


async def send_api_key_revoked_email(
    email: str,
    username: str,
    key_name: str,
    key_prefix: str,
) -> bool:
    """Security notification when an API key is revoked."""
    body = f"""
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your API key <strong>"{key_name}"</strong>
    (<code style="background:#f5f5f5;padding:2px 6px;border-radius:3px;">{key_prefix}••••</code>)
    has been revoked.</p>
    <p>Any applications using this key will receive <code>401 Unauthorized</code> responses immediately.</p>
    <p style="color:#999;font-size:13px;">If you didn't revoke this key, please contact support immediately
    and check your account for unauthorized access.</p>
    """
    html = _base_template(
        title="API key revoked",
        body_html=body,
        cta_url="http://localhost:5173/keys",
        cta_text="Manage API Keys →",
    )
    return await _send_email(email, f"MeterFlow: API key '{key_name}' revoked", html)
