frappe.ui.form.on("Payroll Entry", {
    refresh: function(frm){
        if (frm.doc.salary_slips_submitted || (frm.doc.__onload && frm.doc.__onload.submitted_ss)) {
			frm.add_custom_button("Make The Bank Entry", function () {
                make_the_bank_entry(frm);
            }).addClass("btn-primary");
        }
    },
    
})

let make_the_bank_entry = function (frm) {
	var doc = frm.doc;
	if (doc.payment_account) {
		return frappe.call({
			doc: cur_frm.doc,
			method: "make_payment_entry",
			callback: function () {
				frappe.set_route(
					'List', 'Journal Entry', {
						"Journal Entry Account.reference_name": frm.doc.name
					}
				);
			},
			freeze: true,
			freeze_message: __("Creating The Bank Entry......")
		});
	} else {
		frappe.msgprint(__("Payment Account is mandatory"));
		frm.scroll_to_field('payment_account');
	}
};