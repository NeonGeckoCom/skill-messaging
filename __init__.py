# NEON AI (TM) SOFTWARE, Software Development Kit & Application Framework
# All trademark and other rights reserved by their respective owners
# Copyright 2008-2022 Neongecko.com Inc.
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

from adapt.intent import IntentBuilder
from neon_utils.message_utils import request_from_mobile
from neon_utils.skills.common_message_skill import CommonMessageSkill, CMSMatchLevel
from neon_utils.user_utils import get_message_user
from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
import phonenumbers
import re


class MessagingSkill(CommonMessageSkill):
    def __init__(self, **kwargs):
        CommonMessageSkill.__init__(self, **kwargs)
        self.drafts = {}

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(network_before_load=False,
                                   internet_before_load=False,
                                   gui_before_load=False,
                                   requires_internet=True,
                                   requires_network=True,
                                   requires_gui=False,
                                   no_internet_fallback=False,
                                   no_network_fallback=False,
                                   no_gui_fallback=True)

    # TODO: Move to __init__ after ovos-workshop stable release
    def initialize(self):
        draft_email_intent = IntentBuilder("DraftEmailIntent")\
            .optionally("Neon").require("draft").require("email") \
            .optionally("message").build()
        self.register_intent(draft_email_intent, self.handle_send_email)

        self.add_event("neon.messaging.confirmation",
                       self.handle_confirm_message)

    def CMS_handle_send_message(self, message):
        self.make_active()
        LOG.debug(message.data)
        # utterance = message.data.get("request")
        data = message.data.get("skill_data")
        kind = data.get("kind")
        if not kind:
            LOG.error(f"callback with no kind! {data}")
        elif kind == "sms":
            self.handle_send_sms(message)
        elif kind == "email":
            self.handle_send_email(message)
        elif kind == "klat":
            self.handle_send_private(message)

    def CMS_match_message_phrase(self, request, context):
        """
        Common Messaging skill match evaluation
        :param request: (str) user input
        :return: (dict) confidence, optional: kind, recipient, message, subject
        """
        return_data = {}
        if self.voc_match(request, "klat"):
            return_data["conf"] = CMSMatchLevel.EXACT
            return_data["kind"] = "klat"
        elif self.voc_match(request, "email"):
            return_data["conf"] = CMSMatchLevel.EXACT
            return_data["kind"] = "email"
        elif self.voc_match(request, "sms"):
            return_data["conf"] = CMSMatchLevel.EXACT
            return_data["kind"] = "sms"
        else:
            recipient, message, conf = self._extract_content_sms(request)
            if conf == CMSMatchLevel.MEDIA:
                return_data["kind"] = "sms"
            if recipient and message:
                return_data["conf"] = conf
                return_data["recipient"] = recipient
                return_data["message"] = message
            elif recipient:
                return_data["conf"] = CMSMatchLevel.LOOSE
                return_data["recipient"] = recipient
            else:
                recipient, subject = self._extract_content_email(request)
                return_data["kind"] = "email"
                if recipient and subject:
                    return_data["conf"] = CMSMatchLevel.MEDIA
                    return_data["recipient"] = recipient
                    return_data["subject"] = subject
                elif recipient:
                    return_data["conf"] = CMSMatchLevel.LOOSE
                    return_data["recipient"] = recipient
                else:
                    return_data = None
        return return_data

    def CMS_handle_place_call(self, message):
        self.make_active()
        self.handle_place_call(message)

    def CMS_match_call_phrase(self, contact, context):
        contact_as_number = re.findall(r'\d', contact)
        if len(contact_as_number) >= 7:
            name = contact
            number = "".join(contact_as_number)
            confidence = CMSMatchLevel.EXACT
        else:
            name = contact
            number = None
            confidence = CMSMatchLevel.MEDIA
        return {"conf": confidence, "number": number, "recipient": name, "kind": "call"}

    def handle_confirm_message(self, message):
        # LOG.debug(message.data)
        try:
            user = message.data.get("sender")
            draft = self.drafts[user]
            message.context["klat_data"] = draft["context"]["klat_data"]
            LOG.debug(f"message.data={message.data}")
            LOG.debug(f"draft={draft}")
            if message.data.get("contact_data") and message.data.get("contact_data") != "None":
                contact_data: dict = message.data.get("contact_data")
                LOG.debug(f"contact_data={contact_data}")
                if len(contact_data) > 1:
                    # TODO: Disambiguate multiple contacts here
                    pass
                LOG.debug(contact_data.keys())
                LOG.debug(list(contact_data.keys()))
                contact = list(contact_data.keys())[0]
                LOG.debug(contact)
                draft["recipient"] = contact

                if draft["kind"] in ("text message", "call"):
                    # Get phone number in priority order
                    if "mobile" in contact_data[contact]:
                        address = contact_data[contact]["mobile"]
                    elif "work mobile" in contact_data[contact]:
                        address = contact_data[contact]["work mobile"]
                    elif "home" in contact_data[contact]:
                        address = contact_data[contact]["home"]
                    elif "work" in contact_data[contact]:
                        address = contact_data[contact]["work"]
                    elif "other" in contact_data[contact]:
                        address = contact_data[contact]["other"]
                    elif "phone" in contact_data[contact]:
                        address = contact_data[contact]["phone"]
                    else:
                        address = None
                    draft["number"] = address

                elif draft["kind"] == "email":
                    if "email" in contact_data[contact]:
                        address = contact_data[contact]["email"]
                    else:
                        address = None

                else:
                    LOG.warning(f'requested send {draft["kind"]}')
                    address = None

            elif draft["kind"] == "email" and "@" in draft["recipient"]:
                LOG.debug("email to email address")
                address = draft["recipient"]
                contact = address
            elif draft["kind"] == "text message" and draft["recipient"].replace('-', '').isnumeric():
                LOG.debug("text message to phone number")
                address = draft["recipient"]
                try:
                    contact = phonenumbers.format_number(phonenumbers.parse(draft["recipient"], "US"),
                                                         phonenumbers.PhoneNumberFormat.NATIONAL)
                except Exception as e:
                    LOG.error(e)
                    contact = address
            elif draft["kind"] == "call":
                address = draft["number"].strip()
                # contact = draft["recipient"]
                contact = phonenumbers.format_number(phonenumbers.parse(draft["recipient"], "US"),
                                                     phonenumbers.PhoneNumberFormat.NATIONAL)
                if address == draft["recipient"]:
                    address = contact
            else:
                LOG.warning("No recipient found!")
                address = None
                contact = None

            LOG.debug(f"DM: draft={draft}")
            if address:
                if draft["kind"] == "email":
                    msg = draft["subject"]
                elif draft["kind"] == "text message":
                    msg = draft["message"]
                else:
                    msg = None
                LOG.debug(f"msg={msg}")
                draft["recipient"] = address
                if contact == address:
                    speak_addr = ""
                else:
                    speak_addr = f"({address})"
                LOG.debug(speak_addr)
                LOG.debug(draft["kind"])
                if draft["kind"] == "call":
                    self.speak_dialog("ConfirmCall", {"name": contact, "number": speak_addr},
                                      private=True, message=message)
                    draft["name"] = contact
                else:
                    self.speak_dialog("ConfirmMessage", {"kind": draft["kind"], "name": contact,
                                                         "address": speak_addr, "message": msg},
                                      private=True, message=message)
                    if draft["kind"] == "email":
                        self.speak_dialog("ConfirmEmail", private=True, message=message)
                    else:
                        self.speak_dialog("ConfirmSend", private=True, message=message)
            elif draft["recipient"]:
                LOG.debug(f"DM: no contact or address for: {draft}")
                if draft["kind"] == "email":
                    addr_type = "email address"
                elif draft["kind"] == "text message":
                    addr_type = "phone number"
                else:
                    addr_type = "contact info"
                LOG.debug(draft)
                LOG.debug(draft["recipient"])
                self.speak_dialog("ContactNotFound", {"kind": addr_type, "recipient": draft["recipient"]}, private=True)
                self.drafts.pop(user)
            else:
                self.speak_dialog("ErrorDialog", private=True)
                self.drafts.pop(user)
        except Exception as e:
            LOG.error(e)
            self.speak_dialog("ErrorDialog", private=True)

    def handle_send_email(self, message):
        LOG.debug(message.data)
        user = get_message_user(message)
        # if self.neon_in_request(message) and message.context["mobile"]:
        if request_from_mobile(message):
            # if self.server:
            #     user = nick(message.context["flac_filename"])
            # LOG.debug(f"DM: {self.drafts[user]}")
            self.drafts[user] = {"kind": "email",
                                 "recipient": "",
                                 "subject": "",
                                 "body": "",
                                 "context": message.context,
                                 # "flac_filename": message.context["flac_filename"],
                                 "next_input": "recipient"}

            # Check for data from CMS match
            match_data = message.data.get("skill_data")
            recipient = match_data.get("recipient")
            subject = match_data.get("subject")
            if not recipient and not subject:
                recipient, subject = self._extract_content_email(message.context["cc_data"].get("raw_utterance"))

            # Continue to body of email
            if recipient and subject:
                self.drafts[user]["recipient"] = recipient
                self.drafts[user]["subject"] = subject
                self.drafts[user]["next_input"] = "body"
                self.speak_dialog("GetEmailBody", private=True, expect_response=True)
            elif recipient:
                self.drafts[user]["recipient"] = recipient
                self.drafts[user]["next_input"] = "subject"
                self.speak_dialog("GetEmailSubject", private=True, expect_response=True)
            else:
                self.speak_dialog("GetRecipientAddress", {"kind": "email"}, private=True, expect_response=True)
        else:
            # TODO: Yagmail implementation see mycroft.api.CouponEmail
            self.speak_dialog("OnlyMobile", {"action": "send emails"}, private=True)
            # self.speak("I'm only able to send emails from mobile devices right now.")

    def handle_send_sms(self, message):
        LOG.debug(message)
        user = get_message_user(message)
        # if self.neon_in_request(message) and message.context["mobile"]:
        if request_from_mobile(message):
            # flac_filename = message.context["flac_filename"]
            # if self.server:
            #     user = nick(flac_filename)
            # LOG.debug(f"DM: {self.drafts[user]}")

            # Check for data from CMS match
            match_data = message.data.get("skill_data")
            recipient = match_data.get("recipient")
            sms = match_data.get("message")
            if not recipient and not sms:
                recipient, sms, _ = self._extract_content_sms(message.data.get("request"))
            # recipient, sms = self._extract_content_sms(message.data.get("utterance"))
            if recipient and sms:
                self.drafts[user] = {"kind": "text message",
                                     "recipient": recipient,
                                     "message": sms,
                                     "context": message.context,
                                     # "flac_filename": flac_filename,
                                     "next_input": "confirmation"}
                if request_from_mobile(message):
                    pass
                    # TODO
                    # self.mobile_skill_intent("get_contact", {"recipient": recipient}, message)
                    # self.socket_io_emit('get_contact', f"&recipient={recipient}",
                    #                     message.context["flac_filename"])
                else:
                    self.speak_dialog("OnlyMobile", {"action": "send text messages"}, private=True)
                    # self.speak("This skill is currently only available for Android users.")
                # self._send_sms(message, user)
            elif recipient:
                self.drafts[user] = {"kind": "text message",
                                     "recipient": recipient,
                                     "message": "",
                                     "context": message.context,
                                     # "flac_filename": flac_filename,
                                     "next_input": "message"}
                self.speak("What is the message?", private=True, expect_response=True)
            else:
                self.drafts[user] = {"kind": "text message",
                                     "recipient": "",
                                     "message": "",
                                     "context": message.context,
                                     # "flac_filename": flac_filename,
                                     "next_input": "recipient"}
                self.speak_dialog("GetRecipientAddress", {"kind": "email"}, private=True, expect_response=True)
        else:
            self.speak_dialog("OnlyMobile", {"action": "send text messages"}, private=True)
            # self.speak("I'm only able to send text messages from mobile devices right now.")

    def handle_place_call(self, message):
        if message.context.get("mobile"):
            user = get_message_user(message)
            # flac_filename = message.context["flac_filename"]
            # if self.server:
            #     user = nick(flac_filename)
            call_data = message.data["skill_data"]
            LOG.debug(call_data)
            number = call_data["number"]
            recipient = call_data["recipient"]
            self.drafts[user] = {"kind": "call",
                                 "recipient": recipient,
                                 "number": number,
                                 "context": message.context}
            if number:
                message.data["sender"] = user
                self.handle_confirm_message(message)
            # else:
                # TODO
                # self.mobile_skill_intent("get_contact", {"recipient": recipient}, message)
                # self.socket_io_emit('get_contact', f"&recipient={recipient}",
                #                     message.context["flac_filename"])
        else:
            LOG.debug(message.data["skill_data"])
            self.speak_dialog("OnlyMobile", {"action": "call phone numbers"}, private=True)

    def handle_send_private(self, message):
        pass
        # TODO: Draft and send private message via Klat DM

    def converse(self, message=None):
        utterances = message.data.get("utterances")
        LOG.info(f"utterances={utterances}")
        LOG.debug(f"message.data={message.data}")
        user = get_message_user(message)
        # if self.server:
        #     user = nick(message.context["flac_filename"])

        # Check if user has started a draft
        if self.drafts and user in self.drafts:
            data = self.drafts[user]
            LOG.debug(data)

            # Email Draft
            if data["kind"] == "email":
                # Parse Email Address
                if data["next_input"] == "recipient":
                    data["recipient"] = str(utterances[0]).strip().replace(' ', '.')
                    data["next_input"] = "subject"
                    self.speak_dialog("GetEmailSubject", private=True, expect_response=True)
                # Add Subject Line
                elif data["next_input"] == "subject":
                    data["subject"] = str(utterances[0]).strip()
                    data["next_input"] = "body"
                    self.speak_dialog("GetEmailBody", private=True, expect_response=True)
                # Email Draft Finished
                elif data["next_input"] == "body" and utterances[0] == "done":
                    # self.speak("Email Complete")
                    LOG.info(data)
                    data["next_input"] = "confirmation"
                    # self.speak("Would you like to send your message?")
                    if request_from_mobile(message):
                        pass
                        # TODO
                        # self.mobile_skill_intent("get_contact", {"recipient": data['recipient']}, message)
                        # self.socket_io_emit('get_contact', f"&recipient={data['recipient']}",
                        #                     message.context["flac_filename"])
                    else:
                        self.speak_dialog("ConfirmMessage", {"kind": "email",
                                                             "name": data["recipient"],
                                                             "address": "",
                                                             "message": data["subject"]},
                                          private=True, expect_response=True)
                        self.speak_dialog("ConfirmSend", private=True, expect_response=True)
                elif data["next_input"] == "confirmation":
                    if [word for word in ("no", "cancel", "discard", "nope", "stop", "don't") if word in utterances[0]]:
                        self.speak_dialog("DiscardDraft", private=True)
                        self.drafts.pop(user)
                    elif [word for word in ("yes", "confirm", "affirmative", "send", "okay", "go", "sure", "ok")
                          if word in utterances[0]]:
                        self._send_email(message, user)
                    else:
                        return False
                # Append input to Email Body
                else:
                    data["body"] += str(utterances[0]) + "\n"
            # SMS Draft
            elif data["kind"] == "text message":
                if data["next_input"] == "recipient":
                    data["recipient"] = str(utterances[0]).strip()
                    data["next_input"] = "message"
                    self.speak("What is the message?", private=True, expect_response=True)
                elif data["next_input"] == "message":
                    data["message"] = str(utterances[0]).strip()
                    data["next_input"] = "confirmation"
                    # TODO
                    # self.mobile_skill_intent("get_contact", {"number": data['recipient']}, message)
                    # self.socket_io_emit('get_contact', f"&number={data['recipient']}",
                    #                     message.context["flac_filename"])
                elif data["next_input"] == "confirmation":
                    # Check if send is declined
                    if self.voc_match(utterances[0], "no"):
                        # if [word for word in ("no", "cancel", "discard", "nope", "stop", "don't")
                        #     if word in utterances[0]]:
                        self.speak_dialog("DiscardDraft", private=True)
                        self.drafts.pop(user)
                    # Check if send is approved
                    elif self.voc_match(utterances[0], "yes"):
                        # elif [word for word in ("yes", "confirm", "affirmative", "send", "okay", "go", "sure", "ok")
                        #       if word in utterances[0]]:
                        self._send_sms(message, user)
                    # Not a response, not converse
                    else:
                        return False
            elif data["kind"] == "call":
                LOG.debug("Call response")
                if self.voc_match(utterances[0], "no"):
                    self.speak_dialog("DiscardDraft", private=True)
                    self.drafts.pop(user)
                elif self.voc_match(utterances[0], "yes"):
                    LOG.debug("Call confirmed!")
                    self._place_call(message, user)
                else:
                    return False
            return True
        return False

    def _place_call(self, message, user):
        data = self.drafts[user]
        self.drafts.pop(user)
        LOG.debug(f"data={data}")
        number = data.get("number")
        name = data.get("name")
        self.speak(f"Calling {name}.", private=True)  # TODO: Dialog file DM
        if request_from_mobile(message):
            num = ''.join(re.findall(r'\d', number))
            # TODO
            # self.mobile_skill_intent("call", {"number": num}, message)
            # self.socket_io_emit('call', f"&number={num}", message.context["flac_filename"])

    def _send_sms(self, message, user):
        self.speak_dialog("TextSent")  # TODO: Private?
        data = self.drafts[user]
        recipient = data["recipient"]
        if any(x.isalpha() for x in recipient):
            LOG.error("Recipient is not a number!")
        else:
            recipient = re.sub('[^\d]+', '', recipient).strip()
        LOG.info(recipient)
        content = data["message"]
        self.drafts.pop(user)

        if request_from_mobile(message):
            pass
            # TODO
            # self.mobile_skill_intent("sms", {"number": recipient,
            #                                  "text": content}, message)
            # self.socket_io_emit('sms', f"&number={recipient}&text={content}", message.context["flac_filename"])

    def _send_email(self, message, user):
        self.speak_dialog("EmailSent", private=True)
        data = self.drafts[user]
        recipient = data["recipient"]
        subject = data["subject"]
        body = data["body"]
        self.drafts.pop(user)
        LOG.info(f"Send Email: {data}")
        # TODO
        # if request_from_mobile(message):
        #     self.mobile_skill_intent("email", {"recipient": recipient,
        #                                        "subject": subject,
        #                                        "body": body}, message)
        #     # self.socket_io_emit('email', f"&recipient={recipient}&subject={subject}&body={body}",
        #     #                     message.context["flac_filename"])
        # else:
        #     pass
        #     # # TODO: Send here DM
        #     # self.bus.emit(Message("neon.email", {"title": data["subject"],
        #     #                                      "email": data["recipient"],
        #     #                                      "body": data["body"]}))

    @staticmethod
    def _extract_content_sms(utt):
        """
        Attempts to parse SMS recipient and message, optionally returning either or both
        @param utt: (String) input text
        @return: (String?, String?) recipient, message
        """
        LOG.debug(utt)
        try:
            # Parse out recipient
            if "to" in utt.split():
                remainder = utt.split(" to ", 1)[1]
            else:
                return None, None
            LOG.debug(remainder)
            recipient = remainder.split()[0]
            LOG.debug(recipient)
            remainder = " ".join(remainder.split()[1:])
            LOG.debug(remainder)
            # Parse out message

            if "that says " in remainder:
                recipient_to_append, message = remainder.split("that says ", 1)
                recipient = " ".join([recipient, recipient_to_append]).strip()
                conf = CMSMatchLevel.MEDIA
            elif "saying " in remainder:
                recipient_to_append, message = remainder.split("saying ", 1)
                recipient = " ".join([recipient, recipient_to_append]).strip()
                conf = CMSMatchLevel.MEDIA
            elif len(remainder) <= 1:
                message = None
                recipient = " ".join((recipient, remainder))
                conf = CMSMatchLevel.MEDIA
            else:
                message = remainder
                conf = CMSMatchLevel.LOOSE
        except Exception as e:
            LOG.error(e)
            recipient, message = None, None
            conf = None
        LOG.debug(f"recipient={recipient} | message={message}")
        return recipient, message, conf

    @staticmethod
    def _extract_content_email(utt):
        LOG.debug(utt)
        if "to" in utt.split():
            remainder = utt.split(" to ", 1)[1]
        else:
            return None, None
        LOG.debug(remainder)

        if "subject" in remainder.split():
            recipient_extended, subject = remainder.split(" subject ", 1)
            LOG.debug(f"recip_ext={recipient_extended} | subject={subject}")
            if "with" in recipient_extended.split():
                recipient = recipient_extended.split(" with", 1)[0]
            else:
                recipient = recipient_extended
            LOG.debug(f"recipient={recipient}")
            # return recipient, subject
        else:
            recipient = remainder
            subject = None

        # Parse out email words
        if recipient:
            if "dot" in recipient.split():
                recipient = recipient.replace(" dot ", ".")
            if "at" in recipient.split():
                recipient = recipient.replace(" at ", "@").lower()
            if "@" in recipient:
                # Look at domain (i.e. .com, .co.uk)
                recipient_prefix = recipient.split("@", 1)[0].replace(" ", "")
                recipient_domain = recipient.split("@", 1)[1].split(".")[0].replace(" ", "")
                tld_parts = recipient.split("@", 1)[1].split(".")[1:]
                domain_parts = [part.split()[0] for part in tld_parts]
                tld = ".".join(domain_parts)
                recipient = f"{recipient_prefix}@{recipient_domain}.{tld}"
            LOG.info(f"DM: {recipient}")
        return recipient, subject

    def stop(self):
        pass
