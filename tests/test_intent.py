"""Tests for parse_intent (mocked Anthropic API)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from render.types import Intent, PathwayProposal


def _mock_instructor_response(mode="simulation_explicit", family="ode", engine="scipy_ode"):
    """Build a mock _IntentExtraction-like object."""
    mock = MagicMock()
    mock.mode = mode
    mock.family = family
    mock.engine = engine
    mock.parameters = {"system": "exponential_decay", "t_end": 10.0, "y0": [1.0]}
    mock.user_stated_constraints = []
    mock.assumptions = ["Default initial conditions"]
    mock.confidence = 0.85
    mock.resources_cores = 1
    mock.resources_memory_gb = 4.0
    mock.resources_walltime_hours = 1.0
    mock.resources_gpu = False
    return mock


def _mock_pathway_response():
    mock = MagicMock()
    pw1 = MagicMock(); pw1.engine="scipy_ode"; pw1.family="ode"
    pw1.description="ODE"; pw1.estimated_cost="seconds"; pw1.fidelity="high"; pw1.assumptions=[]; pw1.status="certified"
    pw2 = MagicMock(); pw2.engine="emcee_mcmc"; pw2.family="mcmc"
    pw2.description="MCMC"; pw2.estimated_cost="minutes"; pw2.fidelity="probabilistic"; pw2.assumptions=[]; pw2.status="certified"
    mock.pathways=[pw1,pw2]; mock.recommendation="Use scipy_ode for deterministic result."
    return mock


@patch("render.intent.nlp.instructor")
@patch("render.intent.nlp.anthropic")
def test_parse_intent_simulation_explicit(mock_anthropic, mock_instructor):
    from render.intent import parse_intent

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_instructor_client = MagicMock()
    mock_instructor.from_anthropic.return_value = mock_instructor_client
    mock_instructor_client.messages.create.return_value = _mock_instructor_response()

    intent, proposal = parse_intent(
        "Simulate exponential decay for 10 seconds",
        available_families=["ode","epi"],
        available_engines=["scipy_ode","harmonic_oscillator"],
        model="claude-haiku-4-5-20251001",
        api_key="test-key",
    )
    assert isinstance(intent, Intent)
    assert intent.family == "ode"
    assert intent.engine == "scipy_ode"
    assert intent.mode == "simulation_explicit"
    assert proposal is None


@patch("render.intent.nlp.instructor")
@patch("render.intent.nlp.anthropic")
def test_parse_intent_property_driven(mock_anthropic, mock_instructor):
    from render.intent import parse_intent

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_instructor_client = MagicMock()
    mock_instructor.from_anthropic.return_value = mock_instructor_client

    mock_instructor_client.messages.create.side_effect = [
        _mock_instructor_response(mode="property_driven", engine=""),
        _mock_pathway_response(),
    ]

    intent, proposal = parse_intent(
        "What is the best way to model water at 300K?",
        available_families=["ode","md"],
        available_engines=["scipy_ode","openmm_md"],
        model="claude-haiku-4-5-20251001",
        api_key="test-key",
    )
    assert isinstance(intent, Intent)
    assert intent.mode == "property_driven"
    assert isinstance(proposal, PathwayProposal)
    assert len(proposal.pathways) >= 2


@patch("render.intent.nlp.instructor")
@patch("render.intent.nlp.anthropic")
def test_parse_intent_confidence_field(mock_anthropic, mock_instructor):
    from render.intent import parse_intent

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_instructor_client = MagicMock()
    mock_instructor.from_anthropic.return_value = mock_instructor_client
    mock_instructor_client.messages.create.return_value = _mock_instructor_response()

    intent, _ = parse_intent(
        "Simulate ODE",
        available_families=["ode"],
        available_engines=["scipy_ode"],
        model="claude-haiku-4-5-20251001",
        api_key="test-key",
    )
    assert 0.0 <= intent.confidence <= 1.0


@patch("render.intent.nlp.instructor")
@patch("render.intent.nlp.anthropic")
def test_parse_intent_resources_populated(mock_anthropic, mock_instructor):
    from render.intent import parse_intent

    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_instructor_client = MagicMock()
    mock_instructor.from_anthropic.return_value = mock_instructor_client
    mock_instructor_client.messages.create.return_value = _mock_instructor_response()

    intent, _ = parse_intent(
        "Run ODE simulation",
        available_families=["ode"],
        available_engines=["scipy_ode"],
        model="claude-haiku-4-5-20251001",
        api_key="test-key",
    )
    from render.types import ResourceSpec
    assert isinstance(intent.resources, ResourceSpec)
    assert intent.resources.cores_per_node >= 1
