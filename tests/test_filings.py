import pandas as pd

from vjb.filings import expand_by_fein, match_employers, norm
from vjb.report import verdict, verdict_h1b


def test_norm():
    assert norm("Stripe, Inc.") == "STRIPE"
    assert norm("D. E. Shaw & Co., L.P.") == "D E SHAW"
    assert norm("OpenAI OpCo, LLC") == "OPENAI OPCO"
    assert norm("Visa U.S.A. Inc.") == "VISA"
    assert norm("Skechers U.S.A., Inc. II") == "SKECHERS II"
    assert norm("U.S. Bancorp") == "BANCORP"


def test_match_prefix_and_blocks():
    names = {"OpenAI OpCo, LLC", "Robinhood Markets, Inc.", "Compass Group USA", "Sierra Nevada Corporation",
             "Sierra Technologies, Inc.", "Space Exploration Technologies Corp.", "Millennium Pharmaceuticals, Inc.",
             "Millennium Management LLC", "HARVEY AI CORPORATION", "Harvey & Company LLC"}
    m = match_employers(["OpenAI", "Robinhood", "Compass", "Sierra", "SpaceX", "Millennium", "Harvey"], names)
    assert m["OpenAI"] == {"OpenAI OpCo, LLC"}
    assert m["Robinhood"] == {"Robinhood Markets, Inc."}
    assert m["Compass"] == set()
    assert m["Sierra"] == {"Sierra Technologies, Inc."}
    assert m["SpaceX"] == {"Space Exploration Technologies Corp."}
    assert m["Millennium"] == {"Millennium Management LLC"}
    assert m["Harvey"] == {"HARVEY AI CORPORATION"}


def test_fein_expansion():
    df = pd.DataFrame({"employer": ["Stripe, Inc.", "Stripe Payments Co", "Other LLC"], "fein": ["11-1", "11-1", "22-2"]})
    m = expand_by_fein({"Stripe": {"Stripe, Inc."}}, df)
    assert m["Stripe"] == {"Stripe, Inc.", "Stripe Payments Co"}


def test_verdicts():
    assert verdict("none", 12, 40) == "likely"
    assert verdict("none", 3, 40) == "possible"
    assert verdict("none", 0, 0) == "unknown"
    assert verdict("no_sponsorship", 50, 50) == "no"
    assert verdict_h1b("transfer_only", 0, 0) == "yes"
    assert verdict_h1b("none", 6, 10) == "likely"
