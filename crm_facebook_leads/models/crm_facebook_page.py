import logging

import requests

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CrmFacebookPage(models.Model):
    _name = 'crm.facebook.page'
    _description = 'Facebook Page'

    name = fields.Char(required=True)
    access_token = fields.Char(required=True, string='Page Access Token')
    form_ids = fields.One2many('crm.facebook.form', 'page_id', string='Lead Forms')

    webhook_url = fields.Char(
        compute='_compute_webhook_info', string='Webhook Callback URL',
        help="Paste this into Meta -> Webhooks -> Callback URL.")
    webhook_verify_token = fields.Char(
        compute='_compute_webhook_info', string='Webhook Verify Token',
        help="Paste this into Meta -> Webhooks -> Verify Token. "
             "Change it in Settings > Technical > System Parameters "
             "(facebook.webhook.verify_token).")

    def _compute_webhook_info(self):
        icp = self.env['ir.config_parameter'].sudo()
        base_url = icp.get_param('web.base.url') or ''
        token = icp.get_param('facebook.webhook.verify_token') or ''
        for rec in self:
            rec.webhook_url = '%s/facebook/leadgen/webhook' % base_url
            rec.webhook_verify_token = token

    def form_processing(self, response):
        if not response.get('data'):
            return
        for form in response['data']:
            if self.form_ids.filtered(lambda f: f.id_facebook_form == form['id']):
                continue
            self.form_ids.create({
                'name': form['name'],
                'id_facebook_form': form['id'],
                'page_id': self.id}).get_fields()

        if response.get('paging', {}).get('next'):
            self.form_processing(requests.get(response['paging']['next']).json())

    def get_forms(self):
        """Pull this Page's lead forms.

        The upstream version returned silently on any Graph error (form_processing
        just checks for a 'data' key), so a bad token looked identical to success.
        Surface the error instead.
        """
        self.ensure_one()
        fb_api = self.env['ir.config_parameter'].sudo().get_param('facebook.api.url')
        url = fb_api + self.name + "/leadgen_forms"
        _logger.info('>>> get_forms | page=%s', self.name)

        try:
            response = requests.get(
                url, params={'access_token': self.access_token}, timeout=30).json()
        except Exception as e:
            _logger.exception('*** get_forms request failed')
            raise UserError(_("Could not reach the Facebook Graph API:\n\n%s") % e)

        if response.get('error'):
            err = response['error']
            _logger.error('*** Graph API error on get_forms: %s', err)
            raise UserError(_(
                "Facebook returned an error:\n\n"
                "Message: %(msg)s\n"
                "Type: %(type)s\n"
                "Code: %(code)s\n\n"
                "Tip: /leadgen_forms needs a PAGE access token, not a User or System "
                "User token. Derive one with:\n"
                "GET /%(page)s?fields=access_token&access_token=<SYSTEM_USER_TOKEN>"
            ) % {
                'msg': err.get('message'),
                'type': err.get('type'),
                'code': err.get('code'),
                'page': self.name,
            })

        self.form_processing(response)
        _logger.info('<<< get_forms done | %s form(s) linked', len(self.form_ids))
