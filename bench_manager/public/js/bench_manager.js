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

		var awaitingOutputMessage = __("Command running… awaiting output");
		var state = {
			target: target,
			output: "",
			in_progress: false,
			last_update: null,
			awaiting_output_timer: null,
			awaiting_output: false,
			received_output: false,
		};

		target.innerHTML = "";
		dialog.show();
		dialog.$wrapper.find(".modal-dialog").css("width", "800px");

		function append_output(message) {
			if (!message) {
				return;
			}
			state.output += message;
			if (!state.last_update) {
				state.last_update = setTimeout(function () {
					state.last_update = null;
					update_console(state);
				}, 200);
			}
		}

		function clear_awaiting_output() {
			if (state.awaiting_output_timer) {
				clearTimeout(state.awaiting_output_timer);
				state.awaiting_output_timer = null;
			}
			if (!state.awaiting_output) {
				return;
			}
			state.awaiting_output = false;
			state.output = state.output.replace(
				awaitingOutputMessage + "\n",
				""
			);
			update_console(state);
		}

		append_output(__("Command started") + "\n");
		state.awaiting_output_timer = setTimeout(function () {
			if (!state.awaiting_output && !state.received_output) {
				state.awaiting_output = true;
				append_output(awaitingOutputMessage + "\n");
			}
		}, 2000);

		frappe.realtime.subscribe(key);
		frappe.realtime.on("bench_manager_command", function (output) {
			if (output && typeof output === "object" && output.type === "progress") {
				state.received_output = true;
				clear_awaiting_output();
				var percent = Math.max(0, Math.min(100, output.percent || 0));
				var label = output.label || output.stage || "";
				progressWrapper.show();
				progressLabel.text(label);
				progressBar.css("width", percent + "%");
				progressBar.attr("aria-valuenow", percent);
				progressBar.text(percent + "%");
				if (output.stage === "complete") {
					append_output(__("Command finished successfully") + "\n");
				}
				if (output.stage === "failed") {
					append_output(__("Command failed") + "\n");
				}
				return;
			}

			if (typeof output !== "string") {
				return;
			}

			state.received_output = true;
			clear_awaiting_output();
			if (output === "\r") {
				state.in_progress = true;
				update_console(state);
				state.output = state.output.split("\n").slice(0, -1).join("\n") + "\n";
				return;
			}

			if (output === "\n") {
				state.in_progress = false;
			} else {
				append_output(output);
			}

			if (state.in_progress) {
				return;
			}
		});

		return dialog;
	};
})();
