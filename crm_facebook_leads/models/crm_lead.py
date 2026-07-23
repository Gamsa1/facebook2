import logging
from datetime import datetime, timedelta, timezone
from urllib import parse

import requests

from odoo import api, fields, models

_logger = logging.getLogger()


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    id_facebook_lead = fields.Char(string="Facebook Lead ID", readonly=True)
    facebook_page_id = fields.Many2one(
        'crm.facebook.page', related='facebook_form_id.page_id', store=True)
    facebook_form_id = fields.Many2one('crm.facebook.form', readonly=True)
    facebook_adset_id = fields.Many2one('utm.adset', readonly=True)
    facebook_date_create = fields.Datetime(readonly=True)
    facebook_is_organic = fields.Boolean(readonly=True)

    _facebook_lead_unique = models.Constraint(
        'unique(id_facebook_lead)', 'This Facebook lead already exists!')

    def get_ad(self, lead):
        ad_obj = self.env['utm.medium']
        if not lead.get('ad_id'):
            return ad_obj
        fb_ad = ad_obj.search([('id_facebook_ad', '=', lead['ad_id'])], limit=1)
        if not fb_ad:
            return ad_obj.create({
                'id_facebook_ad': lead['ad_id'],
                'name': lead['ad_name'],
            }).id

        return fb_ad.id

    def get_adset(self, lead):
        ad_obj = self.env['utm.adset']
        if not lead.get('adset_id'):
            return ad_obj
        fb_adset = ad_obj.search([('id_facebook_adset', '=', lead['adset_id'])], limit=1)
        if not fb_adset:
            return ad_obj.create({'id_facebook_adset': lead['adset_id'], 'name': lead['adset_name'], }).id

        return fb_adset.id

    def get_campaign(self, lead):
        campaign_obj = self.env['utm.campaign']
        if not lead.get('campaign_id'):
            return campaign_obj
        fb_camp = campaign_obj.search([('id_facebook_campaign', '=', lead['campaign_id'])], limit=1)
        if not fb_camp:
            return campaign_obj.create({
                'id_facebook_campaign': lead['campaign_id'],
                'name': lead['campaign_name']
            }).id

        return fb_camp.id

    def _prepare_lead_creation(self, lead, form):
        vals, notes = self.get_fields_from_data(lead, form)
        if not vals.get('email_from') and lead.get('email'):
            vals['email_from'] = lead['email']
        if not vals.get('contact_name') and lead.get('full_name'):
            vals['contact_name'] = lead['full_name']
        if not vals.get('phone') and lead.get('phone_number'):
            vals['phone'] = lead['phone_number']
        vals.update({
            'id_facebook_lead': lead['id'],
            'facebook_is_organic': lead['is_organic'],
            'name': self.get_opportunity_name(vals, lead, form),
            'description': "\n".join(notes),
            'team_id': form.team_id and form.team_id.id,
            'campaign_id': form.campaign_id and form.campaign_id.id or
            self.get_campaign(lead),
            'source_id': form.source_id and form.source_id.id,
            'medium_id': form.medium_id and form.medium_id.id or
            self.get_ad(lead),
            'user_id': form.team_id and form.team_id.user_id and form.team_id.user_id.id or False,
            'facebook_adset_id': self.get_adset(lead),
            'facebook_form_id': form.id,
            'facebook_date_create': lead['created_time'].split('+')[0].replace('T', ' ')
        })
        return vals

    def lead_creation(self, lead, form):
        vals = self._prepare_lead_creation(lead, form)
        return self.create(vals)

    def get_opportunity_name(self, vals, lead, form):
        if not vals.get('name'):
            vals['name'] = '%s - %s' % (form.name, lead['id'])
        return vals['name']

    def get_fields_from_data(self, lead, form):
        vals, notes = {}, []
        form_mapping = form.mappings.filtered("odoo_field_id").mapped('facebook_field')
        unmapped_fields = []
        for name, value in lead.items():
            if name not in form_mapping:
                unmapped_fields.append((name, value))
                continue
            odoo_field = form.mappings.filtered(lambda m: m.facebook_field == name).odoo_field_id
            notes.append('%s: %s' % (odoo_field.field_description, value))
            if odoo_field.ttype == 'many2one':
                related_value = self.env[odoo_field.relation].search([('display_name', '=', value)])
                vals.update({odoo_field.name: related_value and related_value.id})
            elif odoo_field.ttype in ('float', 'monetary'):
                vals.update({odoo_field.name: float(value)})
            elif odoo_field.ttype == 'integer':
                vals.update({odoo_field.name: int(value)})
            # TODO: separate date & datetime into two different conditionals
            elif odoo_field.ttype in ('date', 'datetime'):
                vals.update({odoo_field.name: value.split('+')[0].replace('T', ' ')})
            elif odoo_field.ttype == 'selection':
                vals.update({odoo_field.name: value})
            elif odoo_field.ttype == 'boolean':
                vals.update({odoo_field.name: value == 'true' if value else False})
            else:
                vals.update({odoo_field.name: value})

        # NOTE: Doing this to put unmapped fields at the end of the description
        for name, value in unmapped_fields:
            notes.append('%s: %s' % (name, value))

        return vals, notes

    def process_lead_field_data(self, lead):
        field_data = lead.pop('field_data')
        lead_data = dict(lead)
        lead_data.update([
            (ld['name'], ld['values'][0])
            for ld in field_data
            if ld.get('name') and ld.get('values')
        ])
        return lead_data

    def lead_processing(self, response, form):
        """Walk every page, then create leads NEWEST FIRST.

        The Graph /leads edge has no sort parameter, so we page through everything
        and order by created_time descending ourselves. Matters most on the very
        first sync, when there may be a backlog -- the sales team sees the freshest
        leads at the top of the pipeline instead of last.

        Also fixes the upstream infinite loop: `response` was never reassigned, so
        it re-read page 1's paging.next forever once a form had >1 page.
        """
        all_leads = []
        pages = 0
        while True:
            data = response.get('data') or []
            if not data:
                break
            pages += 1
            all_leads.extend(data)

            next_url = (response.get('paging') or {}).get('next')
            if not next_url:
                break
            response = requests.get(next_url, timeout=30).json()
            if response.get('error'):
                _logger.error('*** Form %s: Graph error while paging: %s',
                              form.name, response['error'])
                break

        # Meta returns created_time as ISO-8601, always +0000 -- so a plain string
        # sort is chronologically correct. Newest first.
        all_leads.sort(key=lambda l: l.get('created_time') or '', reverse=True)

        _logger.info('--- Form %s | %s page(s), %s lead(s) fetched, processing newest first',
                     form.name, pages, len(all_leads))

        created = 0
        # Commit in chunks so a failure late on doesn't discard everything already done.
        CHUNK = 100
        for i in range(0, len(all_leads), CHUNK):
            with self.env.cr.savepoint():
                for lead in all_leads[i:i + CHUNK]:
                    lead = self.process_lead_field_data(lead)
                    existing_lead = self.with_context(active_test=False).search(
                        [('id_facebook_lead', '=', lead.get('id'))], limit=1)
                    if existing_lead:
                        continue
                    self.lead_creation(lead, form)
                    created += 1

        _logger.info('+++ Form %s | %s new lead(s) created', form.name, created)
        return created

    def _process_leadgen_webhook(self, value):
        """Handle one `leadgen` change from Meta's webhook.

        `value` looks like:
            {"leadgen_id": "...", "form_id": "...", "page_id": "...",
             "ad_id": "...", "created_time": 1234567890}

        Meta only gives us the ID -- we fetch the actual lead from the Graph API,
        then hand it to the same lead_creation() the cron uses, so field mapping
        and UTM attribution are identical on both paths.
        """
        leadgen_id = value.get('leadgen_id')
        form_id = value.get('form_id')
        if not leadgen_id or not form_id:
            _logger.warning('*** leadgen webhook missing leadgen_id/form_id: %s', value)
            return False

        _logger.info('>>> Processing leadgen_id=%s form_id=%s', leadgen_id, form_id)

        # --- Idempotency. Meta retries aggressively on slow/failed delivery, and
        # --- the cron may also have picked this lead up already.
        existing = self.with_context(active_test=False).search(
            [('id_facebook_lead', '=', leadgen_id)], limit=1)
        if existing:
            _logger.info('--- Already imported, skipping | lead=%s', existing.id)
            return existing

        form = self.env['crm.facebook.form'].search(
            [('id_facebook_form', '=', form_id)], limit=1)
        if not form:
            _logger.warning('*** No crm.facebook.form matches form_id=%s -- '
                            'run "Get Forms" on the page first', form_id)
            return False

        fb_api = self.env['ir.config_parameter'].sudo().get_param('facebook.api.url')
        response = requests.get(
            fb_api + leadgen_id,
            params={'access_token': form.access_token, 'fields': self.LEADGEN_FIELDS},
            timeout=15,
        ).json()

        if response.get('error'):
            _logger.error('*** Graph API error for leadgen_id=%s: %s',
                          leadgen_id, response['error'])
            return False

        lead_data = self.process_lead_field_data(response)
        lead_data.setdefault('is_organic', False)

        lead = self.lead_creation(lead_data, form)
        _logger.info('+++ Lead created from webhook | lead=%s leadgen_id=%s',
                     lead.id, leadgen_id)
        _logger.info('<<< Done leadgen_id=%s', leadgen_id)
        return lead

    # Re-ask for a short window before last_sync so a lead created while the previous
    # run was mid-flight is never skipped. Dedup on id_facebook_lead makes the overlap free.
    SYNC_OVERLAP_MINUTES = 10

    @api.model
    def get_facebook_leads(self):
        fb_api = self.env['ir.config_parameter'].sudo().get_param('facebook.api.url')
        forms = self.env['crm.facebook.form'].search([('allow_to_sync', '=', True)])
        _logger.info('>>> get_facebook_leads | %s form(s) to sync', len(forms))

        for form in forms:
            # Incremental: only ask for leads newer than our last successful sync.
            # The original hardcoded 2018-09-26, so every run re-downloaded the
            # entire lead history and paginated through all of it.
            if form.last_sync:
                since = form.last_sync - timedelta(minutes=self.SYNC_OVERLAP_MINUTES)
                since_ts = int(since.replace(tzinfo=timezone.utc).timestamp())
            else:
                # First ever run for this form. Don't drag in years of history --
                # only go back this far. Tune via the facebook.initial_sync_days param.
                days = int(self.env['ir.config_parameter'].sudo().get_param(
                    'facebook.initial_sync_days', 30))
                # NOTE: utcnow() returns a NAIVE datetime, and .timestamp() then
                # interprets it as LOCAL time -- silently wrong on any non-UTC host.
                # Use an aware datetime so the epoch we send Meta is always correct.
                since = datetime.now(timezone.utc) - timedelta(days=days)
                since_ts = int(since.timestamp())

            _logger.info('--- Form %s | fetching leads created after %s',
                         form.name, datetime.fromtimestamp(since_ts, tz=timezone.utc))

            url = fb_api + form.id_facebook_form + "/leads"
            params = {
                'access_token': form.access_token,
                'fields':
                    'created_time,field_data,ad_id,ad_name,adset_id,adset_name,'
                    'campaign_id,campaign_name,is_organic',
                'limit': 100,
                'filtering': [{
                    "field": "time_created",
                    "operator": "GREATER_THAN",
                    "value": since_ts,
                }],
            }

            started = fields.Datetime.now()
            try:
                response = requests.get(
                    url, params=parse.urlencode(params), timeout=30).json()
            except Exception:
                _logger.exception('*** Form %s: Graph request failed', form.name)
                continue

            if response.get('error'):
                _logger.error('*** Form %s: Graph API error: %s',
                              form.name, response['error'])
                continue

            self.lead_processing(response, form)
            # Only advance the cursor on a clean run, so a failure re-tries the window.
            form.sudo().last_sync = started

        _logger.info('<<< get_facebook_leads done')
