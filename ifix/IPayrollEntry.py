from erpnext.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry
import frappe
from frappe import _
import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)

from frappe.utils import (
	DATE_FORMAT,
	add_days,
	add_to_date,
	cint,
	comma_and,
	date_diff,
	flt,
	get_link_to_form,
	getdate,
)

class IPayrollEntry(PayrollEntry):
    @frappe.whitelist()
    def fill_employee_details(self):
        self.set("employees", [])
        employees = self.get_emp_list()
        if not employees:
            error_msg = _(
                "No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}<br>Payroll Payable Account: {2}"
            ).format(
                frappe.bold(self.company),
                frappe.bold(self.currency),
                frappe.bold(self.payroll_payable_account),
            )
            if self.branch:
                error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
            if self.department:
                error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
            if self.designation:
                error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
            if self.start_date:
                error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
            if self.end_date:
                error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
            frappe.throw(error_msg, title=_("No employees found"))

        for d in employees:
            self.append("employees", d)

        self.number_of_employees = len(self.employees)
        """
            Inserted by Infinity Systems To Fetch Payment Account From Slalary Structures
        """
        """
        BEGIN
        """
        condition = ""
        if self.payroll_frequency:
            condition = """and payroll_frequency = '%(payroll_frequency)s'""" % {
                "payroll_frequency": self.payroll_frequency
            }

        sal_struct = get_sal_struct_payment_account(
            self.company, self.currency, self.salary_slip_based_on_timesheet, condition
        )
        if sal_struct:
            self.payment_account = sal_struct[0] 
        """
        END
        """
        if self.validate_attendance:
            return self.validate_employee_attendance()

    @frappe.whitelist()
    def make_payment_entry(self):
        self.check_permission("write")

        salary_slip_name_list = frappe.db.sql(
            """ select t1.name from `tabSalary Slip` t1
            where t1.docstatus = 1 and start_date >= %s and end_date <= %s and t1.payroll_entry = %s
            """,
            (self.start_date, self.end_date, self.name),
            as_list=True,
        )

        if salary_slip_name_list and len(salary_slip_name_list) > 0:
            salary_slip_total = 0
            for salary_slip_name in salary_slip_name_list:
                salary_slip = frappe.get_doc("Salary Slip", salary_slip_name[0])
                for sal_detail in salary_slip.earnings:
                    (
                        is_flexible_benefit,
                        only_tax_impact,
                        creat_separate_je,
                        statistical_component,
                    ) = frappe.db.get_value(
                        "Salary Component",
                        sal_detail.salary_component,
                        [
                            "is_flexible_benefit",
                            "only_tax_impact",
                            "create_separate_payment_entry_against_benefit_claim",
                            "statistical_component",
                        ],
                    )
                    if only_tax_impact != 1 and statistical_component != 1:
                        if is_flexible_benefit == 1 and creat_separate_je == 1:
                            self.create_journal_entry(sal_detail.amount, sal_detail.salary_component)
                        else:
                            salary_slip_total += sal_detail.amount
                for sal_detail in salary_slip.deductions:
                    statistical_component = frappe.db.get_value(
                        "Salary Component", sal_detail.salary_component, "statistical_component"
                    )
                    if statistical_component != 1:
                        salary_slip_total -= sal_detail.amount
                """
                Inserted by Infinity Systems To Deduct Loan Installment From Salary Voucher
                """
                """
                BEGIN
                """
                for sal_loan in salary_slip.loans:
                    salary_slip_total = salary_slip_total - sal_loan.total_payment
                """
                END
                """
            if salary_slip_total > 0:
                self.create_journal_entry(salary_slip_total, "salary")

    def make_accrual_jv_entry(self):
        self.check_permission("write")
        earnings = self.get_salary_component_total(component_type="earnings") or {}
        deductions = self.get_salary_component_total(component_type="deductions") or {}
        payroll_payable_account = self.payroll_payable_account
        jv_name = ""
        precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

        if earnings or deductions:
            journal_entry = frappe.new_doc("Journal Entry")
            journal_entry.voucher_type = "Journal Entry"
            journal_entry.user_remark = _("Accrual Journal Entry for salaries from {0} to {1}").format(
                self.start_date, self.end_date
            )
            journal_entry.company = self.company
            journal_entry.posting_date = self.posting_date
            accounting_dimensions = get_accounting_dimensions() or []

            accounts = []
            currencies = []
            payable_amount = 0
            multi_currency = 0
            company_currency = erpnext.get_company_currency(self.company)

            # Earnings
            for acc_cc, amount in earnings.items():
                exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
                    acc_cc[0], amount, company_currency, currencies
                )
                payable_amount += flt(amount, precision)
                accounts.append(
                    self.update_accounting_dimensions(
                        {
                            "account": acc_cc[0],
                            "debit_in_account_currency": flt(amt, precision),
                            "exchange_rate": flt(exchange_rate),
                            "cost_center": acc_cc[1] or self.cost_center,
                            "project": self.project,
                        },
                        accounting_dimensions,
                    )
                )

            # Deductions
            for acc_cc, amount in deductions.items():
                exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
                    acc_cc[0], amount, company_currency, currencies
                )
                payable_amount -= flt(amount, precision)
                accounts.append(
                    self.update_accounting_dimensions(
                        {
                            "account": acc_cc[0],
                            "credit_in_account_currency": flt(amt, precision),
                            "exchange_rate": flt(exchange_rate),
                            "cost_center": acc_cc[1] or self.cost_center,
                            "project": self.project,
                            "reference_type": self.doctype,
                            "reference_name": self.name,
                        },
                        accounting_dimensions,
                    )
                )

            # Payable amount
            exchange_rate, payable_amt = self.get_amount_and_exchange_rate_for_journal_entry(
                payroll_payable_account, payable_amount, company_currency, currencies
            )
            accounts.append(
                self.update_accounting_dimensions(
                    {
                        "account": payroll_payable_account,
                        "credit_in_account_currency": flt(payable_amt, precision),
                        "exchange_rate": flt(exchange_rate),
                        "cost_center": self.cost_center,
                        "reference_type": self.doctype,
                        "reference_name": self.name,
                    },
                    accounting_dimensions,
                )
            )

            journal_entry.set("accounts", accounts)
            if len(currencies) > 1:
                multi_currency = 1
            journal_entry.multi_currency = multi_currency
            journal_entry.title = payroll_payable_account
            journal_entry.save()

            try:
                journal_entry.submit()
                jv_name = journal_entry.name
                self.update_salary_slip_status(jv_name=jv_name)
            except Exception as e:
                if type(e) in (str, list, tuple):
                    frappe.msgprint(e)
                raise
        frappe.msgprint('Journal voucher created successfully.', alert =1)
        return jv_name

    # def create_journal_entry(self, je_payment_amount, user_remark):
    #     payroll_payable_account = self.payroll_payable_account
    #     precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

    #     accounts = []
    #     currencies = []
    #     multi_currency = 0
    #     company_currency = erpnext.get_company_currency(self.company)
    #     accounting_dimensions = get_accounting_dimensions() or []

    #     exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
    #         self.payment_account, je_payment_amount, company_currency, currencies
    #     )
    #     accounts.append(
    #         self.update_accounting_dimensions(
    #             {
    #                 "account": self.payment_account,
    #                 "bank_account": self.bank_account,
    #                 "credit_in_account_currency": flt(amount, precision),
    #                 "exchange_rate": flt(exchange_rate),
    #                 "reference_type": self.doctype,
    #                 "reference_name": self.name,
    #             },
    #             accounting_dimensions,
    #         )
    #     )

    #     exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
    #         payroll_payable_account, je_payment_amount, company_currency, currencies
    #     )
    #     accounts.append(
    #         self.update_accounting_dimensions(
    #             {
    #                 "account": payroll_payable_account,
    #                 "debit_in_account_currency": flt(amount, precision),
    #                 "exchange_rate": flt(exchange_rate),
    #                 "reference_type": self.doctype,
    #                 "reference_name": self.name,
    #             },
    #             accounting_dimensions,
    #         )
    #     )

    #     if len(currencies) > 1:
    #         multi_currency = 1

    #     journal_entry = frappe.new_doc("Journal Entry")
    #     journal_entry.voucher_type = "Bank Entry"
    #     journal_entry.user_remark = _("Payment of {0} from {1} to {2}").format(
    #         user_remark, self.start_date, self.end_date
    #     )
    #     journal_entry.company = self.company
    #     journal_entry.posting_date = self.posting_date
    #     journal_entry.multi_currency = multi_currency

    #     journal_entry.set("accounts", accounts)
    #     """
    #     BEGIN
    #     """
    #     journal_entry.reference_doctype = self.doctype
    #     journal_entry.reference_document = self.name
    #     """
    #     END
    #     """
        
    #     journal_entry.save(ignore_permissions=True)
    #     frappe.msgprint('Journal Entry Created With Reference Name {0}'.format(self.name), alert = 1)

def get_sal_struct_payment_account(company, currency, salary_slip_based_on_timesheet, condition):
    """
        Method to collect all payment_account values in the Salary Structures
    """
    return frappe.db.sql_list(
		"""
		select
			distinct payment_account from `tabSalary Structure`
		where
			docstatus = 1 and
			is_active = 'Yes'
			and company = %(company)s
			and currency = %(currency)s and
			ifnull(salary_slip_based_on_timesheet,0) = %(salary_slip_based_on_timesheet)s
			{condition}""".format(
			condition=condition
		),
		{
			"company": company,
			"currency": currency,
			"salary_slip_based_on_timesheet": salary_slip_based_on_timesheet,
		},
	)
