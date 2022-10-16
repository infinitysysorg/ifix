frappe.ui.form.on("Salary Slip", {
    before_submit: function(frm){
        frappe.throw(__('Please submit from the Payroll Entry!'));
    }
})