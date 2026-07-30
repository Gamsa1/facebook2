import json
import logging
import requests

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class MessengerWebhook(http.Controller):

    # ── Webhook Verification (GET) ─────────────────────────────────────────────

    @http.route('/messenger/webhook', type='http', auth='public',
                methods=['GET'], csrf=False)
    def verify_webhook(self, **kwargs):
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
        try:
            data = json.loads(request.httprequest.data)
            _logger.info('Messenger webhook payload: %s', data)

            obj = data.get('object', '')

            if obj == 'page':
                self._process_entries(data.get('entry', []), source='messenger')
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

        for entry in entries:
            fb_page_id = entry.get('id', '')
            page_record = env['messenger.page'].search([('page_id', '=', fb_page_id)], limit=1)

            if not page_record:
                _logger.warning('Received message for unconfigured Page ID: %s', fb_page_id)
                continue

            page_token = page_record.page_access_token

            for messaging in entry.get('messaging', []):
                sender_psid = messaging.get('sender', {}).get('id', '')
                recipient_psid = messaging.get('recipient', {}).get('id', '')
                message_obj = messaging.get('message', {})
                text = message_obj.get('text', '')
                fb_mid = message_obj.get('mid', '')
                is_echo = bool(message_obj.get('is_echo'))

                if not text:
                    continue

                # Skip duplicate deliveries — Meta retries webhooks on failure/timeout.
                if fb_mid and env['messenger.message.line'].search_count([('fb_mid', '=', fb_mid)]):
                    _logger.info('Skipping duplicate webhook delivery for mid %s', fb_mid)
                    continue

                if sender_psid == fb_page_id:
                    customer_psid = recipient_psid
                else:
                    customer_psid = sender_psid

                conversation_key = f'{fb_page_id}_{customer_psid}'
                is_from_page = is_echo or sender_psid == fb_page_id

                conversation = env['messenger.message'].search(
                    [('conversation_key', '=', conversation_key)], limit=1
                )

                if not conversation:
                    # Brand new customer — look up their name once, on first contact.
                    customer_name = (page_record.name or 'Page') if is_from_page \
                        else self._get_sender_name(customer_psid, page_token, source)

                    default_assignee_id = ICP.get_param('messenger_crm_lead.default_assignee_id')

                    conversation = env['messenger.message'].create({
                        'source': source,
                        'customer_psid': customer_psid,
                        'conversation_key': conversation_key,
                        'sender_name': customer_name,
                        'message_text': text,
                        'is_from_page': is_from_page,
                        'state': 'new',
                        'messenger_page_id': page_record.id,
                        'user_id': int(default_assignee_id) if default_assignee_id else False,
                    })

                    if conversation.user_id:
                        conversation.message_subscribe(partner_ids=conversation.user_id.partner_id.ids)

                line_sender_name = (page_record.name or 'Page') if is_from_page else conversation.sender_name

                env['messenger.message.line'].create({
                    'message_id': conversation.id,
                    'sender_name': line_sender_name,
                    'message_text': text,
                    'is_from_page': is_from_page,
                    'fb_mid': fb_mid,
                })

                conversation.write({
                    'message_text': text,
                    'is_from_page': is_from_page,
                    'received_at': fields.Datetime.now(),
                })

                if auto_lead and not is_from_page and conversation.state == 'new':
                    conversation.action_convert_to_lead()

    def _get_sender_name(self, psid, page_token, source):
        if not page_token or not psid:
            return psid or 'Unknown'
        try:
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