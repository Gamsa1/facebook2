import json
import logging
import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MessengerWebhook(http.Controller):

    # ── Webhook Verification (GET) ─────────────────────────────────────────────

    @http.route('/messenger/webhook', type='http', auth='public',
                methods=['GET'], csrf=False)
    def verify_webhook(self, **kwargs):
        """
        Meta calls this URL with a GET request to verify the webhook.
        We echo back hub.challenge if the verify_token matches.
        """
        ICP = request.env['ir.config_parameter'].sudo()
        verify_token = ICP.get_param('messenger_crm_lead.verify_token', '')

        hub_mode = kwargs.get('hub.mode')
        hub_verify_token = kwargs.get('hub.verify_token')
        hub_challenge = kwargs.get('hub.challenge', '')

        if hub_mode == 'subscribe' and hub_verify_token == verify_token:
            _logger.info('Messenger webhook verified successfully.')
            return request.make_response(
                hub_challenge,
                headers=[('Content-Type', 'text/plain')]
            )
        _logger.warning('Messenger webhook verification failed.')
        return request.make_response('Forbidden', status=403)

    # ── Incoming Messages (POST) ───────────────────────────────────────────────

    @http.route('/messenger/webhook', type='http', auth='public',
                methods=['POST'], csrf=False)
    def receive_message(self, **kwargs):
        """
        Meta sends all incoming Messenger & Instagram DM messages here as POST.
        We parse the payload and store (optionally auto-convert to Lead).
        """
        try:
            data = json.loads(request.httprequest.data)
            _logger.info('Messenger webhook payload: %s', data)

            obj = data.get('object', '')

            # Facebook Messenger
            if obj == 'page':
                self._process_entries(data.get('entry', []), source='messenger')

            # Instagram DM
            elif obj == 'instagram':
                self._process_entries(data.get('entry', []), source='instagram')

            return request.make_response(
                json.dumps({'status': 'ok'}),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            _logger.error('Error processing messenger webhook: %s', str(e))
            return request.make_response('Error', status=500)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _process_entries(self, entries, source):
        env = request.env(su=True)
        ICP = env['ir.config_parameter']
        auto_lead = str(ICP.get_param('messenger_crm_lead.auto_lead', 'False')).lower() in ('1', 'true', 'yes')
        page_token = ICP.get_param('messenger_crm_lead.page_access_token', '')

        for entry in entries:
            for messaging in entry.get('messaging', []):
                sender_psid = messaging.get('sender', {}).get('id', '')
                message_obj = messaging.get('message', {})
                text = message_obj.get('text', '')

                if not text:
                    continue  # skip non-text (stickers, reactions, etc.)

                # Try to fetch sender name from Graph API
                sender_name = self._get_sender_name(sender_psid, page_token, source)

                # Save to messenger.message
                msg = env['messenger.message'].create({
                    'source': source,
                    'sender_id': sender_psid,
                    'sender_name': sender_name,
                    'message_text': text,
                    'state': 'new',
                })

                # Auto-create lead if setting is on
                if auto_lead:
                    msg.action_convert_to_lead()

    def _get_sender_name(self, psid, page_token, source):
        """Call Meta Graph API to get the sender's display name."""
        if not page_token or not psid:
            return psid or 'Unknown'
        try:
            if source == 'messenger':
                url = f'https://graph.facebook.com/v19.0/{psid}'
            else:
                url = f'https://graph.facebook.com/v19.0/{psid}'
            resp = requests.get(url, params={
                'fields': 'name',
                'access_token': page_token,
            }, timeout=5)
            if resp.ok:
                return resp.json().get('name', psid)
        except Exception as e:
            _logger.warning('Could not fetch sender name: %s', e)
        return psid
