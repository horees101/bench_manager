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

		var wrapper = $(dialog.get_field("console").wrapper);
		var progressWrapper = $(
			'<div class="bench-manager-progress" style="display:none; margin-bottom: 10px;">' +
				'<div class="text-muted small" data-progress-label></div>' +
				'<div class="progress" style="margin-top: 6px;">' +
					'<div class="progress-bar" role="progressbar" style="width: 0%"></div>' +
				'</div>' +
			'</div>'
		).appendTo(wrapper);

		var progressLabel = progressWrapper.find("[data-progress-label]");
		var progressBar = progressWrapper.find(".progress-bar");

		var target = $('<pre class="console"><code></code></pre>')
			.appendTo(wrapper)
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
			if (output && typeof output === "object" && output.type === "progress") {
				var percent = Math.max(0, Math.min(100, output.percent || 0));
				var label = output.label || output.stage || "";
				progressWrapper.show();
				progressLabel.text(label);
				progressBar.css("width", percent + "%");
				progressBar.attr("aria-valuenow", percent);
				progressBar.text(percent + "%");
				return;
			}

			if (typeof output !== "string") {
				return;
			}

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
