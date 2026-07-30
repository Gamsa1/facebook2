from odoo import fields, models


class MessengerMessageLine(models.Model):
    _name = 'messenger.message.line'
    _description = 'Individual Message Within a Messenger Conversation'
    _order = 'sent_at asc'

    message_id = fields.Many2one('messenger.message', string='Conversation',
                                 required=True, ondelete='cascade', index=True)
    sender_name = fields.Char(string='Sender')
    message_text = fields.Text(string='Message')
    is_from_page = fields.Boolean(string='From Page', default=False)
    sent_at = fields.Datetime(string='Sent At', default=fields.Datetime.now, index=True)
    fb_mid = fields.Char(string='Facebook Message ID', index=True,
                         help='Used to detect and skip duplicate webhook deliveries.')