import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MessengerMessage(models.Model):
    _name = 'messenger.message'
    _description = 'Messenger / Instagram Conversation'
    _order = 'received_at desc'
    _rec_name = 'sender_name'

    # ── Source ────────────────────────────────────────────────────────────────
    source = fields.Selection([
        ('messenger', 'Facebook Messenger'),
        ('instagram', 'Instagram DM'),
    ], string='Source', required=True, default='messenger', readonly=True)

    # ── Customer / conversation identity ─────────────────────────────────────
    customer_psid = fields.Char(string='Customer PSID', required=True, readonly=True, index=True)
    conversation_key = fields.Char(string='Conversation Key', required=True, readonly=True,
                                   index=True,
                                   help='page_id + customer_psid — uniquely identifies this '
                                        'customer\'s conversation with this Page, forever.')
    sender_name = fields.Char(string='Customer Name', default='Unknown',
                              help='Set once from the customer\'s Facebook profile; never '
                                   'overwritten by Page replies.')

    _conversation_key_unique = models.Constraint(
        'unique(conversation_key)',
        'A conversation record for this customer already exists — messages should be '
        'appended to it, not duplicated.',
    )

    # ── Latest activity (quick preview, for list views) ─────────────────────
    message_text = fields.Text(string='Latest Message', readonly=True)
    is_from_page = fields.Boolean(string='Last Message From Page', readonly=True, default=False,
                                  help='True if the most recent message in this conversation '
                                       'was sent by the Page (i.e. you already replied).')
    received_at = fields.Datetime(string='Last Activity', readonly=True,
                                  default=fields.Datetime.now)

    # ── Full thread ───────────────────────────────────────────────────────────
    line_ids = fields.One2many('messenger.message.line', 'message_id', string='Conversation')

    # ── CRM ───────────────────────────────────────────────────────────────────
    lead_id = fields.Many2one('crm.lead', string='CRM Lead', readonly=True,
                              ondelete='set null')
    state = fields.Selection([
        ('new', 'New'),
        ('converted', 'Converted to Lead'),
        ('ignored', 'Ignored'),
    ], string='Status', default='new', required=True)

    # ── Page ──────────────────────────────────────────────────────────────────
    messenger_page_id = fields.Many2one('messenger.page', string='Page', readonly=True)
    page_name = fields.Char(related='messenger_page_id.name', string='Page Name',
                            store=True, readonly=True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_convert_to_lead(self):
        """1-Click: Convert this conversation to a CRM Lead (or reopen the existing one)."""
        self.ensure_one()
        if self.state == 'converted' and self.lead_id:
            return self._open_lead()

        conversation_text = '\n'.join(
            f"[{line.sent_at}] {'Page' if line.is_from_page else self.sender_name}: "
            f"{line.message_text}"
            for line in self.line_ids.sorted('sent_at')
        ) or self.message_text

        started_at = self.line_ids and self.line_ids.sorted('sent_at')[0].sent_at or self.received_at

        lead_vals = {
            'name': f'[{self.source.capitalize()}] {self.sender_name}',
            'contact_name': self.sender_name,
            'description': (
                f'Source: {dict(self._fields["source"].selection)[self.source]}\n'
                f'Page: {self.page_name or "N/A"}\n'
                f'Customer PSID: {self.customer_psid}\n'
                f'Started: {started_at}\n\n'
                f'Conversation:\n{conversation_text}'
            ),
            'type': 'lead',
        }
        lead = self.env['crm.lead'].create(lead_vals)
        self.write({'state': 'converted', 'lead_id': lead.id})
        _logger.info('Converted conversation %s to CRM Lead %s', self.id, lead.id)
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
        """Batch: convert all selected new conversations to leads."""
        for msg in self.filtered(lambda m: m.state == 'new'):
            msg.action_convert_to_lead()
        return True