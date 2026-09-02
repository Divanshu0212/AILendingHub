"""The two answer types, and the invention the gateway cannot commit.

These tests exist because the gateway is the one component in this repository
whose output leaves the process. Every other package refuses in Python, where the
refusal is visible to the next caller; a gateway refusal has to survive
serialisation, because what reaches a screen is the JSON and not the exception.

So they pin three things: that an attribution cannot be built without a real
model behind it, that a refusal cannot be built without a ticket and an owner,
and that both survive `to_json` intact.
"""

from __future__ import annotations

import unittest

from lending_hub.gateway.contract import (
    Attributed,
    FormattedNumber,
    GatewayContractError,
    ModelAttribution,
    Unavailable,
)


class TestModelAttribution(unittest.TestCase):
    def test_empty_model_id_is_refused(self):
        """The triplet is the client's precondition for rendering a number.

        `frontend/src/lib/gateway/provenance.ts` throws on a model-derived value
        whose modelId is absent or empty, so a gateway that emitted one would
        produce a response no screen can display. Refusing at construction means
        the failure lands on the handler that tried it rather than on the browser.
        """
        with self.assertRaises(GatewayContractError):
            ModelAttribution(model_id="", model_version="1.0.0", decision_log_id="dl_1")

    def test_empty_version_is_refused(self):
        with self.assertRaises(GatewayContractError):
            ModelAttribution(model_id="application_pd", model_version="", decision_log_id=None)

    def test_null_decision_log_id_is_allowed(self):
        """Nullable for one reason, and it is not convenience.

        A dashboard aggregate or a batch EWS evaluation is model-derived and
        belongs to no decision. Forging a decision id for it would put entries in
        the audit trail that correspond to no decision — so null is the honest
        value and the UI suppresses the deep link.
        """
        a = ModelAttribution("portfolio_pd", "2.1", None)
        self.assertIsNone(a.to_json()["decisionLogId"])

    def test_for_model_refuses_an_artifact_that_names_nothing(self):
        """The only supported route to an attribution takes an artifact.

        Passing two strings would let any caller name any model; taking an
        artifact means the id in a response resolves to something the registry
        knows, which is what makes the audit deep-link land on the right card.
        """

        class Nameless:
            name = ""
            version = ""

        with self.assertRaises(GatewayContractError):
            ModelAttribution.for_model(Nameless(), decision_log_id="dl_1")

    def test_json_keys_are_the_client_s_camel_case(self):
        """The wire contract is the client's, not Python's.

        A snake_case triplet passes `hasAttribution`'s object check and fails
        every field test, so the client would throw with a message about a
        missing triplet on a response that has one.
        """
        keys = set(ModelAttribution("m", "1", "dl").to_json())
        self.assertEqual(keys, {"modelId", "modelVersion", "decisionLogId"})


class TestFormattedNumber(unittest.TestCase):
    def test_display_is_required(self):
        """The client renders `display` and never formats `amount`.

        Phase 7 §8 puts the rounding of a repayment figure on the backend
        because it is a disclosure decision. An empty display therefore renders
        as a blank where a figure should be, rather than falling back to the raw
        float — which is why it is refused here instead.
        """
        with self.assertRaises(GatewayContractError):
            FormattedNumber(amount=1234.5, display="")

    def test_currency_is_omitted_rather_than_null_for_a_ratio(self):
        """`currency?` is optional in the TypeScript, so absent and null differ."""
        self.assertNotIn("currency", FormattedNumber(0.12, "12%").to_json())
        self.assertEqual(FormattedNumber(1.0, "₹1.00", "INR").to_json()["currency"], "INR")


class TestUnavailable(unittest.TestCase):
    def test_every_field_is_required(self):
        """A refusal with no ticket and no owner is a shrug.

        The whole reason `Unavailable` is a type rather than an error string is
        that a screen can render "Credit Policy has not ratified LH-504" and
        cannot render "unavailable". Dropping either field collapses it back to
        the second.
        """
        for missing in ("capability", "ticket", "owner", "reason"):
            kwargs = {
                "capability": "feasible offer set",
                "ticket": "LH-504",
                "owner": "Credit Policy",
                "reason": "caps unratified",
            }
            kwargs[missing] = ""
            with self.subTest(missing=missing), self.assertRaises(GatewayContractError):
                Unavailable(**kwargs)

    def test_it_is_an_exception_so_a_handler_can_raise_it(self):
        """Raised by the handler, rendered by the router.

        The alternative — returning a union type — puts the burden on every
        handler to remember to propagate it, and the one that forgets returns a
        refusal object where the client expects a payload.
        """
        self.assertIsInstance(
            Unavailable("x", "LH-504", "Credit Policy", "why"), Exception
        )

    def test_json_carries_the_discriminator(self):
        body = Unavailable("offers", "LH-504", "Credit Policy", "why").to_json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["ticket"], "LH-504")


class TestAttributed(unittest.TestCase):
    def test_a_value_cannot_be_serialised_without_its_attribution(self):
        """There is no constructor that makes an attributed value from a number.

        Mirrors `Attributed<T>`: the pairing is the type, so the only way a
        model-derived number reaches a payload is through an object that already
        holds the model's identity.
        """
        with self.assertRaises(TypeError):
            Attributed(value=720)  # type: ignore[call-arg]

    def test_nested_formatted_number_serialises(self):
        a = Attributed(
            FormattedNumber(0.031, "3.10%"), ModelAttribution("portfolio_pd", "2.1", None)
        )
        self.assertEqual(a.to_json()["value"]["display"], "3.10%")


if __name__ == "__main__":
    unittest.main()
