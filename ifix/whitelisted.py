from erpnext.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry
import frappe

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
                for sal_loan in salary_slip.loans:
                    salary_slip_total = salary_slip_total - sal_loan.total_payment
            if salary_slip_total > 0:
                self.create_journal_entry(salary_slip_total, "salary")


def get_sal_struct_payment_account(company, currency, salary_slip_based_on_timesheet, condition):
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
