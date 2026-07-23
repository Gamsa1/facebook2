# -*- coding: utf-8 -*-
"""Real-time Facebook Lead Ads capture via Meta's `leadgen` webhook.

Meta POSTs a `leadgen_id` the instant someone submits a Lead Ad form. We verify
the payload signature, fetch the full lead from the Graph API, and hand it to the
module's existing mapping logic (`crm.lead.lead_creation`), so field mapping,
UTM campaign/adset/ad attribution and dedup all behave exactly as they do for
the hourly cron.

The cron is intentionally left enabled as a safety net: if the webhook endpoint
is ever unreachable, the next poll backfills whatever was missed.
"""
import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class FacebookLeadgenWebhook(http.Controller):

    # -------------------------------------------------------------------------
    # Signature verification -- BLOCKING. An unsigned or badly signed request is
    # rejected outright; this endpoint is public and writes to the database.
    # -------------------------------------------------------------------------
    def _verify_signature(self, raw_body):
        header = request.httprequest.headers.get('X-Hub-Signature-256', '')
        secret = request.env['ir.config_parameter'].sudo().get_param('facebook.app_secret')

        if not secret:
            _logger.error("*** facebook.app_secret is not set -- rejecting webhook")
            return False
        if not header.startswith('sha256='):
            _logger.warning("*** Missing X-Hub-Signature-256 header -- rejecting")
            return False

        expected = 'sha256=' + hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(header, expected):
            _logger.warning("*** X-Hub-Signature-256 mismatch -- rejecting")
            return False
        return True

    # -------------------------------------------------------------------------
    # GET -- Meta's subscription handshake
    # -------------------------------------------------------------------------
    @http.route('/facebook/leadgen/webhook', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def verify(self, **kw):
        mode = kw.get('hub.mode')
        token = kw.get('hub.verify_token') or ''
        challenge = kw.get('hub.challenge') or ''
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'facebook.webhook.verify_token') or ''

        _logger.info(">>> Webhook verification | mode=%s", mode)

        if mode == 'subscribe' and expected and hmac.compare_digest(token, expected):
            _logger.info("<<< Webhook verified -- echoing challenge")
            return request.make_response(challenge, [('Content-Type', 'text/plain')])

        _logger.warning("*** Webhook verification FAILED -- verify_token mismatch")
        return request.make_response('Forbidden', [('Content-Type', 'text/plain')], status=403)

    # -------------------------------------------------------------------------
    # POST -- leadgen events
    # -------------------------------------------------------------------------
    @http.route('/facebook/leadgen/webhook', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def leadgen(self, **kw):
        raw_body = request.httprequest.get_data()

        if not self._verify_signature(raw_body):
            return request.make_response('Forbidden', [('Content-Type', 'text/plain')], status=403)

        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            _logger.warning("*** Webhook body is not valid JSON")
            return request.make_response('Bad Request', [('Content-Type', 'text/plain')], status=400)

        _logger.info(">>> Leadgen webhook received | object=%s", payload.get('object'))
        Lead = request.env['crm.lead'].sudo()

        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                if change.get('field') != 'leadgen':
                    continue
                value = change.get('value') or {}
                try:
                    Lead._process_leadgen_webhook(value)
                except Exception:
                    # Never 500 back to Meta -- it would retry forever. Log and move on;
                    # the hourly cron will backfill anything we drop here.
                    _logger.exception(
                        "*** Failed processing leadgen_id=%s", value.get('leadgen_id'))

        _logger.info("<<< Leadgen webhook done")
        return request.make_response('EVENT_RECEIVED', [('Content-Type', 'text/plain')])
