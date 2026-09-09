# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2026 Neongecko.com Inc.
# Contributors: Daniel McKnight, Guy Daniels, Elon Gasper, Richard Leeds,
# Regina Bloomstine, Casimiro Ferreira, Andrii Pernatii, Kirill Hrymailo
# BSD-3 License
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import pytest

from threading import Timer
from ovos_bus_client import Message
from neon_minerva.tests.skill_unit_test_base import SkillTestCase


def _node_message(msg_type: str, skill_data: dict, action_key: str,
                  action_supported: bool = True,
                  session_id: str = "node-test-1"):
    return Message(msg_type, {"skill_data": skill_data}, {
        "node": {
            "node_id": "node-test-1",
            "node_name": "Test Node",
            "capabilities": {action_key: action_supported}
        },
        "session": {"session_id": session_id}
    })


def _response(action: str, status="success", error=None,
             session_id="node-test-1"):
    data = {"action": action, "status": status}
    if error:
        data["error"] = error
    return Message("node.invoke_native.response", data,
                   {"session": {"session_id": session_id}})


def _arm_node_reply(bus, response_message):
    """
    `FakeBus.emit` runs handlers synchronously, so replying to
    `node.invoke_native` from inside its own handler would emit the
    response before the helper's `wait_for_message` has subscribed. Reply
    from a short delay instead, after the handler's call stack unwinds.
    """
    def _reply(_m):
        Timer(0.05, lambda: bus.emit(response_message)).start()
    bus.once("node.invoke_native", _reply)


class TestSkillMethods(SkillTestCase):
    def test_00_skill_init(self):
        from neon_utils.skills.common_message_skill import CommonMessageSkill
        self.assertIsInstance(self.skill, CommonMessageSkill)

    def test_send_sms_node_dispatches_with_params(self):
        message = _node_message(
            "SendSMSIntent",
            {"recipient": "5551234567", "message": "On my way"},
            "launch_sms_app")
        emitted = []
        self.skill.bus.once("node.invoke_native",
                            lambda m: emitted.append(m))
        _arm_node_reply(self.skill.bus, _response("launch_sms_app"))

        self.skill.handle_send_sms(message)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].data["action"], "launch_sms_app")
        self.assertEqual(emitted[0].data["params"],
                         {"to": "5551234567", "body": "On my way"})
        # confirm_on_success defaults off; a silent success proves the
        # reply actually arrived rather than the call silently timing out.
        self.skill.speak.assert_not_called()
        self.skill.speak_dialog.assert_not_called()

    def test_send_sms_node_does_not_enter_draft_state(self):
        message = _node_message(
            "SendSMSIntent",
            {"recipient": "5551234567", "message": "On my way"},
            "launch_sms_app")
        _arm_node_reply(self.skill.bus, _response("launch_sms_app"))

        drafts_before = dict(self.skill.drafts)
        self.skill.handle_send_sms(message)

        self.assertEqual(self.skill.drafts, drafts_before)
        self.skill.speak.assert_not_called()
        self.skill.speak_dialog.assert_not_called()

    def test_send_sms_node_unsupported_capability(self):
        # skill-messaging ships native_action_*.dialog files, so the
        # neon-utils helper prefers speak_dialog over its plain-text fallback.
        message = _node_message(
            "SendSMSIntent",
            {"recipient": "5551234567", "message": "On my way"},
            "launch_sms_app", action_supported=False)

        self.skill.handle_send_sms(message)

        self.skill.speak.assert_not_called()
        self.skill.speak_dialog.assert_called_once_with(
            "native_action_not_supported",
            {"action": "launch_sms_app", "description": "the messages app"},
            message=message)

    def test_send_sms_node_missing_content_speaks_error(self):
        message = _node_message("SendSMSIntent", {}, "launch_sms_app")

        self.skill.handle_send_sms(message)

        self.skill.speak_dialog.assert_called_once_with(
            "ErrorDialog", message=message)

    def test_send_email_node_dispatches_with_params(self):
        message = _node_message(
            "DraftEmailIntent",
            {"recipient": "sarah@example.com", "subject": "The project"},
            "launch_email_app")
        emitted = []
        self.skill.bus.once("node.invoke_native",
                            lambda m: emitted.append(m))
        _arm_node_reply(self.skill.bus, _response("launch_email_app"))

        self.skill.handle_send_email(message)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].data["action"], "launch_email_app")
        self.assertEqual(emitted[0].data["params"],
                         {"to": "sarah@example.com",
                          "subject": "The project"})
        self.skill.speak.assert_not_called()
        self.skill.speak_dialog.assert_not_called()

    def test_send_email_node_body_only_omits_subject_key(self):
        message = _node_message(
            "DraftEmailIntent",
            {"recipient": "sarah@example.com", "body": "Running late"},
            "launch_email_app")
        emitted = []
        self.skill.bus.once("node.invoke_native",
                            lambda m: emitted.append(m))
        _arm_node_reply(self.skill.bus, _response("launch_email_app"))

        self.skill.handle_send_email(message)

        self.assertEqual(emitted[0].data["params"],
                         {"to": "sarah@example.com",
                          "body": "Running late"})

    def test_send_email_node_subject_and_body_both_forwarded(self):
        message = _node_message(
            "DraftEmailIntent",
            {"recipient": "sarah@example.com", "subject": "The project",
             "body": "Status update attached."},
            "launch_email_app")
        emitted = []
        self.skill.bus.once("node.invoke_native",
                            lambda m: emitted.append(m))
        _arm_node_reply(self.skill.bus, _response("launch_email_app"))

        self.skill.handle_send_email(message)

        self.assertEqual(emitted[0].data["params"],
                         {"to": "sarah@example.com",
                          "subject": "The project",
                          "body": "Status update attached."})

    def test_send_email_node_unsupported_capability(self):
        message = _node_message(
            "DraftEmailIntent",
            {"recipient": "sarah@example.com", "subject": "The project"},
            "launch_email_app", action_supported=False)

        self.skill.handle_send_email(message)

        self.skill.speak.assert_not_called()
        self.skill.speak_dialog.assert_called_once_with(
            "native_action_not_supported",
            {"action": "launch_email_app", "description": "the email app"},
            message=message)

    def test_send_email_node_missing_recipient_speaks_error(self):
        message = _node_message("DraftEmailIntent",
                                {"subject": "The project"},
                                "launch_email_app")

        self.skill.handle_send_email(message)

        self.skill.speak_dialog.assert_called_once_with(
            "ErrorDialog", message=message)

    def test_send_sms_mobile_path_unaffected_by_node_branch(self):
        # No `context.node`: must take the pre-existing mobile draft path,
        # not the new node branch, and must not emit `node.invoke_native`.
        message = Message("SendSMSIntent",
                          {"skill_data": {"recipient": "5551234567",
                                         "message": "hi"}},
                          {"mobile": True})
        emitted = []
        self.skill.bus.once("node.invoke_native",
                            lambda m: emitted.append(m))

        self.skill.handle_send_sms(message)

        self.assertEqual(emitted, [])
        self.assertIn(None, self.skill.drafts)
        self.skill.drafts.pop(None, None)


if __name__ == '__main__':
    pytest.main()
