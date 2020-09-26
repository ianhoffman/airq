import datetime
import pytz
import typing

from unittest import mock
from twilio.base.exceptions import TwilioRestException

from airq.lib.twilio import TwilioErrorCode
from airq.models.clients import Client
from airq.models.clients import ClientIdentifierType
from airq.models.events import Event
from airq.models.events import EventType
from airq.models.zipcodes import Zipcode
from tests.base import BaseTestCase


class ClientTestCase(BaseTestCase):
    zipcode: typing.Optional[Zipcode] = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.zipcode = Zipcode.query.filter_by(zipcode="97204").first()

    def _make_client(
        self,
        last_activity_at: int = 0,
        last_alert_sent_at: int = 0,
        last_pm25: float = 0.0,
        alerts_disabled_at: int = 0,
        num_alerts_sent: int = 0,
    ) -> Client:
        assert self.zipcode is not None, "Zipcode not set"
        client = Client(
            identifier="+12222222222",
            type_code=ClientIdentifierType.PHONE_NUMBER,
            last_activity_at=last_activity_at,
            zipcode_id=self.zipcode.id,
            last_alert_sent_at=last_alert_sent_at,
            last_pm25=last_pm25,
            alerts_disabled_at=alerts_disabled_at,
            num_alerts_sent=num_alerts_sent,
        )
        self.db.session.add(client)
        self.db.session.commit()
        return client

    def test_maybe_notify(self):
        # Don't notify if pm25 hasn't changed
        client = self._make_client(last_pm25=self.zipcode.pm25)
        self.assertFalse(client.maybe_notify())
        self.assertEqual(0, client.num_alerts_sent)
        self.assertEqual(0, client.last_alert_sent_at)
        self.assertEqual(0, Event.query.count())

        # Don't notify if before 8 AM
        with mock.patch(
            "airq.models.clients.timestamp",
            return_value=datetime.datetime.fromtimestamp(self.timestamp).replace(
                hour=7, minute=59, tzinfo=pytz.timezone("America/Los_Angeles")
            ),
        ):
            self.assertFalse(client.maybe_notify())
        self.assertEqual(0, client.num_alerts_sent)
        self.assertEqual(0, client.last_alert_sent_at)
        self.assertEqual(0, Event.query.count())

        # Don't notify if after 9 PM
        with mock.patch(
            "airq.models.clients.timestamp",
            return_value=datetime.datetime.fromtimestamp(self.timestamp).replace(
                hour=21, minute=0, tzinfo=pytz.timezone("America/Los_Angeles")
            ),
        ):
            self.assertFalse(client.maybe_notify())
        self.assertEqual(0, client.num_alerts_sent)
        self.assertEqual(0, client.last_alert_sent_at)
        self.assertEqual(0, Event.query.count())

        client.last_pm25 += 50
        self.assertTrue(client.maybe_notify())
        self.assertEqual(1, client.num_alerts_sent)
        self.assertEqual(self.timestamp, client.last_alert_sent_at)
        self.assert_event(
            client.id,
            EventType.ALERT,
            zipcode=self.zipcode.zipcode,
            pm25=self.zipcode.pm25,
        )

    def test_filter_eligible_for_sending(self):
        # Don't send if client was messaged less than or equal to two hours ago
        client = self._make_client(
            last_alert_sent_at=self.timestamp - (2 * 60 * 60),
            last_pm25=self.zipcode.pm25 + 50,
        )
        self.assertEqual(0, Client.query.filter_eligible_for_sending().count())

        client.last_alert_sent_at -= 1
        self.db.session.commit()
        self.assertEqual(1, Client.query.filter_eligible_for_sending().count())

        # Don't send if alerts are disabled
        client.alerts_disabled_at = self.timestamp
        self.db.session.commit()
        self.assertEqual(0, Client.query.filter_eligible_for_sending().count())

        # Don't send if client has no zipcode
        client.alerts_disabled_at = 0
        client.zipcode_id = None
        self.db.session.commit()
        self.assertEqual(0, Client.query.filter_eligible_for_sending().count())

    def test_enable_alerts(self):
        client = self._make_client(alerts_disabled_at=self.timestamp)
        client.enable_alerts()
        self.assertEqual(0, client.alerts_disabled_at)
        self.assert_event(
            client.id, EventType.RESUBSCRIBE, zipcode=client.zipcode.zipcode
        )
        self.assertTrue(client.is_enabled_for_alerts)

    def test_disable_alerts(self):
        client = self._make_client(last_pm25=self.zipcode.pm25)
        client.disable_alerts()
        self.assertEqual(self.timestamp, client.alerts_disabled_at)
        self.assertEqual(7.945, client.last_pm25)
        self.assert_event(
            client.id, EventType.UNSUBSCRIBE, zipcode=client.zipcode.zipcode
        )

    def test_update_subscription(self):
        client = self._make_client(last_pm25=self.zipcode.pm25)
        self.assertEqual(self.zipcode.id, client.zipcode_id)
        self.assertEqual(self.zipcode.pm25, client.last_pm25)

        other = Zipcode.query.filter_by(zipcode="97038").first()
        client.update_subscription(other)
        self.assertEqual(other.id, client.zipcode_id)
        self.assertEqual(other.pm25, client.last_pm25)

    def test_send_message_raises_known_error_code(self):
        client = self._make_client()
        self.assertTrue(client.is_enabled_for_alerts)
        self.assertEqual(0, Event.query.count())
        with mock.patch(
            "airq.models.clients.send_sms",
            side_effect=TwilioRestException(
                "", "", code=TwilioErrorCode.OUT_OF_REGION.value
            ),
        ):
            client.send_message("testing")
        client = Client.query.get(client.id)
        self.assertFalse(client.is_enabled_for_alerts)
        self.assert_event(
            client.id, EventType.UNSUBSCRIBE, zipcode=client.zipcode.zipcode
        )

    def test_send_message_raises_unknown_error_code(self):
        client = self._make_client()
        self.assertTrue(client.is_enabled_for_alerts)
        self.assertEqual(0, Event.query.count())
        with mock.patch(
            "airq.models.clients.send_sms",
            side_effect=TwilioRestException("", "", code=77),
        ):
            with self.assertRaises(Exception):
                client.send_message("testing")
        client = Client.query.get(client.id)
        self.assertTrue(client.is_enabled_for_alerts)
        self.assertEqual(0, Event.query.count())
