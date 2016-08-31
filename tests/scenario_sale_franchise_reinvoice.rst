=================================
Sale Franchise Reinovice Scenario
=================================

Imports::
    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax, set_tax_code
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()
    >>> tomorrow = today + relativedelta(days=1)

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install sale_franchise_reinvoice::

    >>> Module = Model.get('ir.module')
    >>> module, = Module.find(
    ...     [('name', '=', 'sale_franchise_reinvoice')])
    >>> module.click('install')
    >>> Wizard('ir.module.install_upgrade').execute('upgrade')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Create account user::

    >>> User = Model.get('res.user')
    >>> Group = Model.get('res.group')
    >>> account_user = User()
    >>> account_user.name = 'Account'
    >>> account_user.login = 'account'
    >>> account_user.main_company = company
    >>> account_group, = Group.find([('name', '=', 'Account Administration')])
    >>> account_user.groups.append(account_group)
    >>> account_user.save()
    >>> account_group, = Group.find([('name', '=', 'Analytic Administration')])
    >>> account_user.groups.append(account_group)
    >>> account_user.save()

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')
    >>> period = fiscalyear.periods[0]

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> payable = accounts['payable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> account_tax = accounts['tax']
    >>> account_cash = accounts['cash']

Create tax::

    >>> Tax = Model.get('account.tax')
    >>> tax = set_tax_code(create_tax(Decimal('.10')))
    >>> tax.save()
    >>> invoice_base_code = tax.invoice_base_code
    >>> invoice_tax_code = tax.invoice_tax_code
    >>> credit_note_base_code = tax.credit_note_base_code
    >>> credit_note_tax_code = tax.credit_note_tax_code

Create party::

    >>> Party = Model.get('party.party')
    >>> party = Party(name='Party')
    >>> party.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'product'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal('40')
    >>> template.cost_price = Decimal('20')
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.customer_taxes.append(tax)
    >>> template.supplier_taxes.append(Tax(tax.id))
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create franchise::

    >>> Franchise = Model.get('sale.franchise')
    >>> franchise = Franchise()
    >>> franchise.code = '1'
    >>> franchise.name = 'Franchise'
    >>> franchise_party = Party(name='Franchise')
    >>> franchise_party.customer_payment_term = payment_term
    >>> franchise_party.supplier_payment_term = payment_term
    >>> franchise_party.save()
    >>> franchise.company_party = franchise_party
    >>> franchise.save()

Create analytic accounts::

    >>> AnalyticAccount = Model.get('analytic_account.account')
    >>> root = AnalyticAccount(type='root', name='Root')
    >>> root.save()
    >>> analytic_account = AnalyticAccount(root=root, parent=root,
    ...     name='Analytic')
    >>> analytic_account.franchise = franchise
    >>> analytic_account.save()

Create invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> invoice = Invoice()
    >>> invoice.type = 'in'
    >>> invoice.party = party
    >>> invoice.payment_term = payment_term
    >>> invoice.invoice_date = today
    >>> invoice.description = 'SUPPLIER DESCRIPTION'
    >>> line = invoice.lines.new()
    >>> line.product = product
    >>> line.description = 'Description'
    >>> line.reinvoice_date = tomorrow
    >>> line.quantity = 5
    >>> line.unit_price = Decimal('40')
    >>> entry, = line.analytic_accounts
    >>> entry.account = analytic_account
    >>> line.analytic_accounts[0].account == analytic_account
    True
    >>> invoice.click('post')
    >>> invoice.number
    u'1'

A new invoice have been created for the sale franchise::

    >>> franchise_invoice, = Invoice.find([
    ...     ('party', '=', franchise_party.id)])
    >>> franchise_invoice.type
    u'out'
    >>> franchise_invoice.invoice_date == tomorrow
    True
    >>> franchise_invoice.description
    u'SUPPLIER DESCRIPTION'
    >>> franchise_invoice.reference
    u'1'
    >>> franchise_line, = franchise_invoice.lines
    >>> franchise_line.product == product
    True
    >>> franchise_line.account == revenue
    True
    >>> franchise_line.analytic_accounts[0].account == analytic_account
    True
    >>> franchise_line.unit_price
    Decimal('40')
    >>> franchise_line.description
    u'Description'
    >>> franchise_invoice.untaxed_amount
    Decimal('200.00')
    >>> franchise_invoice.total_amount
    Decimal('220.00')


Credit the supplier invoice and check reinvoice data is copied correctly::

    >>> credit = Wizard('account.invoice.credit', [invoice])
    >>> credit.execute('credit')
    >>> credit_note, = Invoice.find([
    ...     ('type', '=', 'in_credit_note')])
    ...     ('party', '=', party.id)])
    >>> credit_note_line, = credit_note.lines
    >>> credit_note_line.analytic_accounts.accounts == [analytic_account]
    True
    >>> credit_note_line.reinvoice_date == tomorrow
    True
    >>> credit_note.invoice_date = tomorrow
    >>> credit_note.click('post')
    >>> franchise_credit_note, = Invoice.find([
    ...     ('type', '=', 'out_credit_note')])
    ...     ('party', '=', franchise_party.id)])
    >>> franchise_credit_note.invoice_date == tomorrow
    True
    >>> franchise_credit_note.untaxed_amount
    Decimal('100.00')
    >>> franchise_credit_note.total_amount
    Decimal('110.00')
