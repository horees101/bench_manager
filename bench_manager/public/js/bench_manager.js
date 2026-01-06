// Copyright (c) 2017, Frappe and contributors
// For license information, please see license.txt

(function () {
	"use strict";

	function update_console(state) {
		if (!state.in_progress) {
			state.target.innerHTML = state.output;
		}
	}

	window.console_dialog = function (key) {
		var dialog = new frappe.ui.Dialog({
			title: __("Console"),
			fields: [{ fieldname: "console", fieldtype: "HTML" }],
		});

		var target = $('<pre class="console"><code></code></pre>')
			.appendTo(dialog.get_field("console").wrapper)
			.find("code")
			.get(0);

		var state = {
			target: target,
			output: "",
			in_progress: false,
			last_update: null,
		};

		target.innerHTML = "";
		dialog.show();
		dialog.$wrapper.find(".modal-dialog").css("width", "800px");

		frappe.realtime.on(key, function (output) {
			if (output === "\r") {
				state.in_progress = true;
				update_console(state);
				state.output = state.output.split("\n").slice(0, -1).join("\n") + "\n";
				return;
			}

			if (output === "\n") {
				state.in_progress = false;
			} else {
				state.output += output;
			}

			if (state.in_progress) {
				return;
			}

			if (!state.last_update) {
				state.last_update = setTimeout(function () {
					state.last_update = null;
					update_console(state);
				}, 200);
			}
		});

		return dialog;
	};
})();
