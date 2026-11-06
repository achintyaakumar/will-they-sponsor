import pytest

from vjb.rules import analyze, stance
from vjb.roles import is_us, role_family, seniority

CASES = [
    ("We are unable to sponsor or take over sponsorship of an employment Visa at this time.", "no_sponsorship"),
    ("Applicants must be authorized to work in the U.S. without the need for visa sponsorship now or in the future.", "no_sponsorship"),
    ("Visa sponsorship:\nWe do sponsor visas! However, we aren't able to successfully sponsor visas for every role and every candidate.", "case_by_case"),
    ("Visa sponsorship is available for this position.", "sponsors"),
    ("This position requires an active Secret clearance.", "citizen_only"),
    ("Must be a U.S. citizen due to government contract requirements.", "citizen_only"),
    ("ITAR REQUIREMENTS:\nTo conform to U.S. Government export regulations, applicant must be a (i) U.S. citizen or national, (ii) U.S. lawful, permanent resident.", "citizen_only"),
    ("Must be a U.S. Person due to required access to U.S. export controlled information or facilities.", "citizen_only"),
    ("Candidates must be legally authorized to work in the United States.", "auth_required"),
    ("We are an equal opportunity employer and do not discriminate on the basis of race, citizenship status, or national origin.", "none"),
    ("You will work with executive sponsors across the business.", "none"),
    ("Stripe does not sponsor visas for this role in Canada.", "none"),
    ("This role is not eligible for visa sponsorship.", "no_sponsorship"),
    ("Must have unrestricted authorization to work in the US.", "no_sponsorship"),
    ("We participate in E-Verify.", "none"),
    ("Visa Sponsorship: Not available", "no_sponsorship"),
    ("We offer immigration support including green card sponsorship.", "sponsors"),
    ("Please note that any offer of employment may be conditioned on your authorization to receive software or technology controlled under these U.S. export laws without sponsorship for an export license.", "none"),
    ("Applicants must be legally authorized to work in the posting location for the duration of the internship.", "auth_required"),
    ("For US based roles only, please note the Company may not be able to employ candidates for this role who have United States work authorization related to certain U.S. visa categories, or support future immigration sponsorship.", "case_by_case"),
    ("But if we make you an offer, we will make every reasonable effort to get you a visa, and we retain an immigration lawyer to help with this.", "sponsors"),
    ("Preferred Qualifications\nActive Secret security clearance", "none"),
    ("Those with an active clearance will receive a 10% differential.", "none"),
    ("Regular sponsored professional development opportunities", "none"),
    ("Docker considers visa sponsorship on a case-by-case basis based on business needs.", "case_by_case"),
    ("If your position is employed by another Airbnb entity, your recruiter will inform you what states you are eligible to work from.", "none"),
]


@pytest.mark.parametrize("text,want", CASES)
def test_stance(text, want):
    assert stance(analyze(text)["labels"]) == want


@pytest.mark.parametrize("locs,countries,want", [
    (["San Francisco, CA"], [], True),
    (["London"], [], False),
    (["Remote - US"], [], True),
    (["Toronto, Canada; New York, NY"], [], True),
    (["Bengaluru, India"], [], False),
    (["Remote"], [], None),
    ([], ["United States"], True),
])
def test_is_us(locs, countries, want):
    assert is_us(locs, countries) == want


@pytest.mark.parametrize("title,fam,sen", [
    ("Software Engineer, New Grad", "software", "early"),
    ("Senior Machine Learning Engineer", "data_ml", "senior"),
    ("Solutions Engineer", "other", "mid"),
    ("Mechanical Engineer II", "hardware", "mid"),
    ("Quantitative Researcher Intern", "quant", "intern"),
    ("Product Designer", "product_design", "mid"),
])
def test_roles(title, fam, sen):
    assert role_family(title) == fam
    assert seniority(title) == sen
