# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from collections import defaultdict
from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval, Bool
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.modules.account_invoice.invoice import _TYPE2JOURNAL

__all__ = ['Account', 'Invoice', 'InvoiceLine']
__metaclass__ = PoolMeta


class Account(ModelSQL, ModelView):
    __name__ = 'analytic_account.account'

    franchise = fields.Many2One('sale.franchise', 'Franchise',
        states={
            'invisible': Eval('type') != 'normal',
            },
        depends=['type'])


class Invoice:
    __name__ = 'account.invoice'

    reinvoice_invoices = fields.Function(fields.One2Many('account.invoice',
            None, 'Reinvoice Invoices'),
        'get_reinvoice_invoices')

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._buttons.update({
                'create_franchise_reinvoices': {
                    'invisible': (~Eval('state').in_(['posted', 'paid']) |
                        Eval('type').in_(['out_invoice', 'out_credit_note'])),
                    },
                })

    def get_reinvoice_invoices(self, name):
        return [i.id for i in self.search([
                    ('lines.origin.invoice.id', '=', self.id,
                        'account.invoice.line'),
                    ('type', '=', self.type.replace('in_', 'out_')),
                    ])]

    @classmethod
    def post(cls, invoices):
        super(Invoice, cls).post(invoices)
        if Transaction().context.get('reinvoice', True):
            cls.create_franchise_reinvoices(invoices)

    @classmethod
    @ModelView.button
    def create_franchise_reinvoices(cls, invoices):
        reinvoices = defaultdict(list)
        for invoice in invoices:
            if invoice.reinvoice_invoices:
                continue
            if invoice.type[:2] != 'in':
                continue
            for line in invoice.lines:
                reinvoice_line = line.get_reinvoice_line()
                if reinvoice_line:
                    reinvoices[line.reinvoice_key].append(reinvoice_line)
        to_create = []
        for key, lines in reinvoices.iteritems():
            invoice = cls._get_franchise_invoice(key)
            invoice.lines = (list(getattr(invoice, 'lines', [])) + lines)
            to_create.append(invoice._save_values)
        with Transaction().set_context(reinvoice=False):
            cls.post(cls.create(to_create))

    @classmethod
    def _get_franchise_invoice(cls, key):
        values = dict(key)
        invoice = cls(**values)
        if 'invoice' in values:
            invoice.reference = values['invoice'].number
            invoice.description = values['invoice'].description
        if invoice.party:
            for key, value in invoice.on_change_party().iteritems():
                setattr(invoice, key, value)
        return invoice


class InvoiceLine:
    __name__ = 'account.invoice.line'

    franchise = fields.Function(fields.Many2One('sale.franchise', 'Franchise'),
        'on_change_with_franchise')
    reinvoice_date = fields.Date('Reinvoice Date',
        states={
            # TODO: Uncomment on version > 3.6 as on_change is not working
            #'invisible': ~Bool(Eval('franchise')),
            'invisible': Eval('_parent_invoice', {}).get('type',
                Eval('invoice_type')).in_(['out_invoice', 'out_credit_note'])
            },
        depends=['franchise'])

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        if 'reinvoice_date' not in cls.product.depends:
            # TODO: Uncomment on version > 3.6 as on_change is not working
            required = Bool(Eval('reinvoice_date')) #  & Bool(Eval('franchise'))
            old_required = cls.product.states.get('required')
            if old_required:
                required |= old_required
            cls.product.states['required'] = required
            cls.product.depends.append('reinvoice_date')
            #  cls.product.depends.append('franchise')

    @fields.depends('analytic_accounts')
    def on_change_with_franchise(self, name=None):
        if not self.analytic_accounts:
            return None
        for account in self.analytic_accounts.accounts:
            if account.franchise:
                return account.franchise.id

    @property
    def reinvoice_key(self):
        pool = Pool()
        Journal = pool.get('account.journal')
        if not self.franchise or not self.reinvoice_date:
            return
        type = self.invoice.type.replace('in_', 'out_')
        journals = Journal.search([
                ('type', '=', _TYPE2JOURNAL.get(type or 'out_invoice',
                        'revenue')),
                ], limit=1)
        journal = None
        if journals:
            journal, = journals
        return (
            ('company', self.invoice.company),
            ('currency', self.invoice.company.currency),
            ('party', self.franchise.company_party),
            ('invoice_date', self.reinvoice_date),
            ('invoice', self.invoice),
            ('payment_term', self.invoice.payment_term),
            ('type', type),
            ('journal', journal),
            )

    def get_reinvoice_line(self):
        pool = Pool()
        Selection = pool.get('analytic_account.account.selection')
        if not self.franchise or not self.reinvoice_date or not self.product:
            return
        invoice_line = self.__class__()
        invoice_line.invoice_type = self.invoice.type.replace('in_', 'out_')
        invoice_line.party = self.franchise.company_party
        invoice_line.description = self.description
        invoice_line.quantity = self.quantity
        invoice_line.product = self.product
        invoice_line.origin = self
        for key, value in invoice_line.on_change_product().iteritems():
            setattr(invoice_line, key, value)
        invoice_line.unit_price = self.unit_price
        # Compatibility with account_invoice discount module
        if hasattr(self, 'gross_unit_price'):
            invoice_line.gross_unit_price = self.gross_unit_price
            invoice_line.discount = self.discount
        selection, = Selection.copy([self.analytic_accounts])
        invoice_line.analytic_accounts = selection
        return invoice_line

    def _credit(self):
        line = super(InvoiceLine, self)._credit()
        if line and self.reinvoice_date:
            line['reinvoice_date'] = self.reinvoice_date
        return line
