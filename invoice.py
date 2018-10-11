# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Equal, Eval, Bool
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Account', 'Invoice', 'InvoiceLine']


class Account(ModelSQL, ModelView):
    __name__ = 'analytic_account.account'
    __metaclass__ = PoolMeta

    franchise = fields.Many2One('sale.franchise', 'Franchise',
        states={
            'invisible': Eval('type') != 'normal',
            },
        depends=['type'])


class Invoice:
    __name__ = 'account.invoice'
    __metaclass__ = PoolMeta

    reinvoice_invoices = fields.Function(fields.One2Many('account.invoice',
            None, 'Reinvoice Invoices'),
        'get_reinvoice_invoices')

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls._buttons.update({
                'create_franchise_reinvoices': {
                    'invisible': (~Eval('state').in_(['posted', 'paid']) |
                        Equal(Eval('type'), 'out')),
                    },
                })

    def get_reinvoice_invoices(self, name):
        return [i.id for i in self.search([
                    ('lines.origin.invoice.id', '=', self.id,
                        'account.invoice.line'),
                    ('type', '=', 'out'),
                    ])]

    @classmethod
    def post(cls, invoices):
        super(Invoice, cls).post(invoices)
        if Transaction().context.get('reinvoice', True):
            with Transaction().set_user(0):
                cls.create_franchise_reinvoices(invoices)

    @classmethod
    @ModelView.button
    def create_franchise_reinvoices(cls, invoices):
        pool = Pool()
        Journal = pool.get('account.journal')
        Entry = pool.get('analytic.account.entry')
        reinvoices = []
        for invoice in invoices:
            if invoice.reinvoice_invoices:
                continue
            if invoice.type != 'in':
                continue
            if not invoice.lines:
                continue
            journal, = Journal.search([
                    ('type', '=', 'revenue'),
                    ], limit=1)

            reinvoice = cls()
            reinvoice.company = invoice.company
            reinvoice.journal = invoice.journal
            reinvoice.currency = invoice.company.currency
            reinvoice.payment_term = invoice.payment_term
            reinvoice.type = 'out'
            reinvoice.account = invoice.account
            reinvoice.reference = invoice.number
            reinvoice.description = invoice.description
            reinvoice.invoice_date = [l.reinvoice_date
                for l in invoice.lines
                if l.reinvoice_date][0]
            reinvoice.party = [l.franchise.company_party
                for l in invoice.lines
                if l.franchise and l.franchise.company_party][0]
            reinvoice.on_change_party()

            reinvoice_lines = []
            for line in invoice.lines:
                reinvoice_lines.append(line.get_reinvoice_line())
            if reinvoice_lines:
                reinvoice.lines = reinvoice_lines
                reinvoices.append(reinvoice)
        cls.save(reinvoices)

        with Transaction().set_context(reinvoice=False):
            cls.post(reinvoices)


class InvoiceLine:
    __name__ = 'account.invoice.line'
    __metaclass__ = PoolMeta

    franchise = fields.Function(fields.Many2One('sale.franchise', 'Franchise'),
        'on_change_with_franchise')
    reinvoice_date = fields.Date('Reinvoice Date',
        states={
            # TODO: Uncomment on version > 3.6 as on_change is not working
            # 'invisible': ~Bool(Eval('franchise')),
            'invisible': Eval('_parent_invoice', {}).get('type',
                Eval('invoice_type')) == 'out'
            },
        depends=['franchise'])

    @classmethod
    def __setup__(cls):
        super(InvoiceLine, cls).__setup__()
        if 'reinvoice_date' not in cls.product.depends:
            # TODO: Uncomment on version > 3.6 as on_change is not working
            required = Bool(Eval('reinvoice_date'))
            #  & Bool(Eval('franchise'))
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

        for account in self.analytic_accounts:
            if getattr(account, 'account', False) and (
                    account.account.franchise):
                return account.account.franchise.id

    def get_reinvoice_line(self):
        Entry = Pool().get('analytic.account.entry')

        if not self.franchise or not self.reinvoice_date or not self.product:
            return

        reinvoice_line = self.__class__()
        reinvoice_line.invoice_type = 'out'
        reinvoice_line.account = self.product.template.account_revenue
        reinvoice_line.party = self.franchise.company_party
        reinvoice_line.description = self.description
        reinvoice_line.quantity = self.quantity
        reinvoice_line.type = self.type
        reinvoice_line.origin = self
        reinvoice_line.company = self.company
        reinvoice_line.unit_price = self.unit_price
        reinvoice_line.product = self.product
        reinvoice_line.on_change_product()

        # Compatibility with account_invoice discount module
        if hasattr(self, 'gross_unit_price'):
            reinvoice_line.gross_unit_price = self.gross_unit_price
            reinvoice_line.discount = self.discount

        default = {
            'origin': None,
            }
        analytic_accounts = Entry.copy(list(self.analytic_accounts),
            default=default)
        reinvoice_line.analytic_accounts = analytic_accounts

        return reinvoice_line

    def _credit(self):
        line = super(InvoiceLine, self)._credit()
        if line and self.reinvoice_date:
            line.reinvoice_date = self.reinvoice_date
        return line
