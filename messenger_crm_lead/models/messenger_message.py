import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MessengerMessage(models.Model):
    _name = 'messenger.message'
    _description = 'Incoming Messenger / Instagram DM Message'
    _order = 'received_at desc'
    _rec_name = 'sender_name'

    # ── Source ────────────────────────────────────────────────────────────────
    source = fields.Selection([
        ('messenger', 'Facebook Messenger'),
        ('instagram', 'Instagram DM'),
    ], string='Source', required=True, default='messenger', readonly=True)

    # ── Sender info ───────────────────────────────────────────────────────────
    sender_id = fields.Char(string='Sender ID (PSID)', readonly=True)
    sender_name = fields.Char(string='Sender Name', default='Unknown')

    # ── Message content ───────────────────────────────────────────────────────
    message_text = fields.Text(string='Message', readonly=True)
    received_at = fields.Datetime(string='Received At', readonly=True,
                                  default=fields.Datetime.now)

    # ── CRM ───────────────────────────────────────────────────────────────────
    lead_id = fields.Many2one('crm.lead', string='CRM Lead', readonly=True,
                              ondelete='set null')
    state = fields.Selection([
        ('new', 'New'),
        ('converted', 'Converted to Lead'),
        ('ignored', 'Ignored'),
    ], string='Status', default='new', required=True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_convert_to_lead(self):
        """1-Click: Convert this incoming message to a CRM Lead."""
        self.ensure_one()
        if self.state == 'converted' and self.lead_id:
            # Already converted → open existing lead
            return self._open_lead()

        lead_vals = {
            'name': f'[{self.source.capitalize()}] {self.sender_name}',
            'contact_name': self.sender_name,
            'description': (
                f'Source: {dict(self._fields["source"].selection)[self.source]}\n'
                f'Sender ID: {self.sender_id}\n'
                f'Received: {self.received_at}\n\n'
                f'Message:\n{self.message_text}'
            ),
            'type': 'lead',
        }
        lead = self.env['crm.lead'].create(lead_vals)
        self.write({'state': 'converted', 'lead_id': lead.id})
        _logger.info('Converted messenger message %s to CRM Lead %s', self.id, lead.id)
        return self._open_lead()

    def action_ignore(self):
        self.ensure_one()
        self.write({'state': 'ignored'})

    def action_reset(self):
        self.ensure_one()
        self.write({'state': 'new'})

    def _open_lead(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Lead'),
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
        }

    # ── Batch action ──────────────────────────────────────────────────────────

    def action_convert_all_to_leads(self):
        """Batch: convert all selected new messages to leads."""
        for msg in self.filtered(lambda m: m.state == 'new'):
            msg.action_convert_to_lead()
        return True
