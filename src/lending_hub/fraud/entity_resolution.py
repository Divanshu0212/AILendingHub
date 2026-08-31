"""Entity resolution v1, and the graph it produces for Phase 6.

Phase 1 §4 WS-1.2 Step 1: "Blocking + fuzzy matching: name Jaro–Winkler with
threshold tuned on labeled duplicate pairs `[DATA]`; phone/account exact; address
normalized + geohash. Library: `splink` or `recordlinkage` (**ADR-011**). Output:
entity nodes/edges tables in Gold — schema designed jointly with P6 (GNN reuse)."

The output is not a report
--------------------------
It is the graph Phase 6 trains GraphSAGE and CARE-GNN on. That changes what
matters. A wrong merge creates an edge that does not exist, and a GNN trained on
it learns a fraud ring that is a data-quality artifact — which will be
investigated, and will waste a fraud analyst's week before anyone doubts the
graph. So every edge carries the attribute and the score that created it: "why
are these two linked" is the first question a fraud analyst asks and the first
one a model-risk reviewer asks, and an edge that cannot answer it is not
evidence.

The score is a score, not a probability
---------------------------------------
ADR-0011 chose `splink` for Track B precisely because Fellegi–Sunter emits a
calibrated match *probability*. This Track A matcher emits a weighted similarity,
and :class:`MatchScore` says so in its own field rather than letting a number
between 0 and 1 be mistaken for one. Presenting a similarity as a probability is
the defect `recordlinkage` was rejected for, and reproducing it here would teach
everyone to read the number wrongly before the real one arrives.

The threshold is `[DATA]` and does not exist (LH-209): no labelled duplicate pairs
have been produced by any workstream. :func:`resolve` therefore requires the
threshold to be passed explicitly with its provenance, and a run made on an
unratified threshold is stamped as such all the way into the graph tables.

Workstream: WS-1.2 Step 1 · SRS §5.2 (FR-2), §5.3.3
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from lending_hub.definitions import Pending

#: Standard Jaro-Winkler prefix scaling and cap.
WINKLER_SCALE = 0.1
WINKLER_MAX_PREFIX = 4

#: Geohash precision for address blocking. 6 characters is roughly a 1.2 x 0.6 km
#: cell — small enough that two addresses in one cell are plausibly the same
#: locality, large enough that a geocoding wobble of a few hundred metres does not
#: split a genuine match across two blocks. Blocking precision is a recall
#: parameter: too fine and true matches are never compared at all.
GEOHASH_PRECISION = 6

_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"

MATCH_THRESHOLD = Pending(
    owner="Fraud Head",
    ticket="LH-209",
    note=(
        "the name-similarity threshold, tuned on labelled duplicate pairs. No "
        "labelled pairs exist and no workstream produces them; without them a "
        "threshold is a preference, and every precision claim about entity "
        "resolution rests on it"
    ),
)


class EntityResolutionError(Exception):
    """The resolution cannot be performed as requested."""


class NodeType(str, Enum):
    """Node types in the Gold entity graph. Fixed here for P6 (SRS §5.3.3)."""

    APPLICANT = "applicant"
    PHONE = "phone"
    ADDRESS = "address"
    DEVICE = "device"
    BANK_ACCOUNT = "bank_account"
    EMPLOYER = "employer"


class EdgeType(str, Enum):
    SHARES_PHONE = "shares_phone"
    SHARES_ADDRESS = "shares_address"
    SHARES_DEVICE = "shares_device"
    SHARES_ACCOUNT = "shares_account"
    SHARES_EMPLOYER = "shares_employer"
    NAME_SIMILAR = "name_similar"


def normalise_name(value: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    Deliberately does *not* reorder tokens or strip honorifics. Both are
    locale-dependent transformations that change who matches whom, and doing them
    silently inside a normaliser hides a matching decision inside a formatting
    function.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", stripped.casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalise_phone(value: str) -> str:
    """Digits only, keeping the last ten.

    Keeping the last ten rather than the first: the variable part of a stored
    phone number is the prefix — ``+91``, ``0``, nothing — and the subscriber
    number is the stable tail.
    """
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def normalise_account(value: str) -> str:
    """Alphanumeric, upper-cased, leading zeros preserved.

    Leading zeros are significant in account numbers, so this does not strip
    them — a normaliser that did would merge two different accounts.
    """
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def geohash(latitude: float, longitude: float, precision: int = GEOHASH_PRECISION) -> str:
    """Standard base-32 geohash.

    Interleaved binary subdivision of latitude and longitude, five bits per
    character. The property being used here is that a shared prefix means spatial
    proximity, which is what makes it a blocking key.
    """
    if not -90.0 <= latitude <= 90.0:
        raise EntityResolutionError(f"latitude {latitude} out of range")
    if not -180.0 <= longitude <= 180.0:
        raise EntityResolutionError(f"longitude {longitude} out of range")

    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    out: list[str] = []
    bits = 0
    bit_count = 0
    even = True

    while len(out) < precision:
        if even:
            middle = sum(lon_range) / 2
            if longitude > middle:
                bits = (bits << 1) | 1
                lon_range[0] = middle
            else:
                bits <<= 1
                lon_range[1] = middle
        else:
            middle = sum(lat_range) / 2
            if latitude > middle:
                bits = (bits << 1) | 1
                lat_range[0] = middle
            else:
                bits <<= 1
                lat_range[1] = middle
        even = not even
        bit_count += 1
        if bit_count == 5:
            out.append(_GEOHASH_ALPHABET[bits])
            bits = 0
            bit_count = 0
    return "".join(out)


def jaro(left: str, right: str) -> float:
    """Jaro similarity."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0

    window = max(len(left), len(right)) // 2 - 1
    window = max(window, 0)

    left_matched = [False] * len(left)
    right_matched = [False] * len(right)
    matches = 0

    for i, character in enumerate(left):
        start = max(0, i - window)
        stop = min(i + window + 1, len(right))
        for j in range(start, stop):
            if right_matched[j] or right[j] != character:
                continue
            left_matched[i] = right_matched[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    transpositions = 0
    j = 0
    for i in range(len(left)):
        if not left_matched[i]:
            continue
        while not right_matched[j]:
            j += 1
        if left[i] != right[j]:
            transpositions += 1
        j += 1
    transpositions //= 2

    return (
        matches / len(left)
        + matches / len(right)
        + (matches - transpositions) / matches
    ) / 3.0


def jaro_winkler(left: str, right: str, *, scale: float = WINKLER_SCALE) -> float:
    """Jaro-Winkler: Jaro with a bonus for a shared prefix.

    The prefix bonus is why this is the standard choice for personal names —
    people mistype and abbreviate the *ends* of names far more often than the
    beginnings. It is also why it is a poor choice for identifiers, where the
    discriminating part is often the tail.
    """
    base = jaro(left, right)
    prefix = 0
    for a, b in zip(left[:WINKLER_MAX_PREFIX], right[:WINKLER_MAX_PREFIX]):
        if a != b:
            break
        prefix += 1
    return base + prefix * scale * (1 - base)


@dataclass(frozen=True)
class ApplicationRecord:
    """One application's identity attributes, already tokenised where required."""

    application_id: str
    name: str = ""
    phone: str = ""
    account: str = ""
    device_id: str = ""
    employer: str = ""
    latitude: float | None = None
    longitude: float | None = None
    address_text: str = ""

    def blocking_keys(self) -> set[str]:
        """Keys under which this record is compared to others.

        Blocking is a recall decision, not an efficiency trick. Two records that
        share no key are never compared and therefore never match, whatever their
        similarity — so a missing key is a missed fraud ring, not a slow query.
        """
        keys: set[str] = set()
        phone = normalise_phone(self.phone)
        if phone:
            keys.add(f"phone:{phone}")
        account = normalise_account(self.account)
        if account:
            keys.add(f"account:{account}")
        if self.device_id:
            keys.add(f"device:{self.device_id}")
        if self.latitude is not None and self.longitude is not None:
            keys.add(f"geo:{geohash(self.latitude, self.longitude)}")
        name = normalise_name(self.name)
        if len(name) >= 3:
            # Name-prefix blocking catches pairs sharing no identifier at all,
            # which is the case deliberate identity fraud is built to produce.
            keys.add(f"name3:{name[:3]}")
        return keys


@dataclass(frozen=True)
class MatchScore:
    """Why two records were considered the same entity."""

    left: str
    right: str
    score: float
    is_probability: bool
    """Always False on Track A. The Track B (`splink`) adapter sets it True.

    Kept as an explicit field rather than left to documentation: a similarity and
    a match probability are both numbers in [0, 1], and every downstream report
    that averages, thresholds or plots them needs to know which it has.
    """

    evidence: dict[str, float] = field(default_factory=dict)
    deterministic: bool = False
    """True when an exact identifier matched, which needs no threshold at all."""

    def to_dict(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "score": self.score,
            "is_probability": self.is_probability,
            "deterministic": self.deterministic,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: NodeType
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "attributes": self.attributes,
        }


@dataclass(frozen=True)
class Edge:
    """One link, carrying the evidence that created it."""

    source: str
    target: str
    edge_type: EdgeType
    weight: float = 1.0
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "evidence": self.evidence,
        }


@dataclass
class EntityGraph:
    """The Gold nodes/edges tables. Schema fixed for P6 reuse."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    threshold_ratified: bool = False
    threshold_provenance: str = str(MATCH_THRESHOLD)

    def add_node(self, node: Node) -> None:
        self.nodes.setdefault(node.node_id, node)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def neighbours(self, node_id: str) -> set[str]:
        out: set[str] = set()
        for edge in self.edges:
            if edge.source == node_id:
                out.add(edge.target)
            elif edge.target == node_id:
                out.add(edge.source)
        return out

    def components(self) -> list[set[str]]:
        """Connected components — the cheap, explainable ring signature (SRS §5.3.3.1)."""
        seen: set[str] = set()
        found: list[set[str]] = []
        for node_id in sorted(self.nodes):
            if node_id in seen:
                continue
            stack = [node_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                stack.extend(self.neighbours(current) - component)
            seen |= component
            found.append(component)
        return found

    def to_dict(self) -> dict:
        return {
            "nodes": [self.nodes[n].to_dict() for n in sorted(self.nodes)],
            "edges": [e.to_dict() for e in self.edges],
            "threshold_ratified": self.threshold_ratified,
            "threshold_provenance": self.threshold_provenance,
            "note": (
                "Track A entity graph. Edge weights are similarity scores, not "
                "match probabilities (ADR-0011); the Track B splink adapter "
                "replaces them with calibrated probabilities."
            ),
        }


def candidate_pairs(records: Sequence[ApplicationRecord]) -> set[tuple[str, str]]:
    """Pairs sharing at least one blocking key."""
    blocks: dict[str, list[str]] = {}
    by_id = {record.application_id: record for record in records}
    for record in records:
        for key in record.blocking_keys():
            blocks.setdefault(key, []).append(record.application_id)

    pairs: set[tuple[str, str]] = set()
    for members in blocks.values():
        ordered = sorted(set(members))
        for i, left in enumerate(ordered):
            for right in ordered[i + 1 :]:
                pairs.add((left, right))
    if len(by_id) != len(records):
        raise EntityResolutionError("duplicate application_id in the input records")
    return pairs


def compare(left: ApplicationRecord, right: ApplicationRecord) -> MatchScore:
    """Score one candidate pair.

    Exact identifier matches are reported as ``deterministic``: a shared phone
    number or bank account needs no similarity threshold, and folding it into a
    weighted score would let a strong deterministic signal be diluted by weak
    fuzzy ones.
    """
    evidence: dict[str, float] = {}

    if normalise_phone(left.phone) and normalise_phone(left.phone) == normalise_phone(right.phone):
        evidence["phone"] = 1.0
    if normalise_account(left.account) and normalise_account(left.account) == normalise_account(
        right.account
    ):
        evidence["account"] = 1.0
    if left.device_id and left.device_id == right.device_id:
        evidence["device"] = 1.0
    if left.employer and normalise_name(left.employer) == normalise_name(right.employer):
        evidence["employer"] = 1.0

    left_name, right_name = normalise_name(left.name), normalise_name(right.name)
    if left_name and right_name:
        evidence["name"] = jaro_winkler(left_name, right_name)

    if None not in (left.latitude, left.longitude, right.latitude, right.longitude):
        left_hash = geohash(left.latitude, left.longitude)
        right_hash = geohash(right.latitude, right.longitude)
        shared = 0
        for a, b in zip(left_hash, right_hash):
            if a != b:
                break
            shared += 1
        evidence["address"] = shared / GEOHASH_PRECISION

    deterministic = any(
        evidence.get(key) == 1.0 for key in ("phone", "account", "device")
    )
    score = max(evidence.values()) if evidence else 0.0

    return MatchScore(
        left=left.application_id,
        right=right.application_id,
        score=score,
        is_probability=False,
        evidence=evidence,
        deterministic=deterministic,
    )


def build_graph(
    records: Sequence[ApplicationRecord],
    matches: Iterable[MatchScore],
    *,
    name_threshold: float,
    threshold_ratified: bool,
    threshold_provenance: str = "",
) -> EntityGraph:
    """Assemble the Gold nodes/edges tables from records and scored pairs.

    ``name_threshold`` has no default. Phase 1 requires it tuned on labelled
    duplicate pairs (LH-209), none exist, and a default value in a signature is
    how an untuned threshold becomes the production one — nobody passes the
    argument, and by the time anyone asks, the number has been in the graph for a
    year.
    """
    if not 0.0 <= name_threshold <= 1.0:
        raise EntityResolutionError("name_threshold must be between 0 and 1")
    if threshold_ratified and not threshold_provenance:
        raise EntityResolutionError(
            "a ratified threshold must cite the tuning run or decision that set it"
        )

    graph = EntityGraph(
        threshold_ratified=threshold_ratified,
        threshold_provenance=threshold_provenance or str(MATCH_THRESHOLD),
    )

    for record in records:
        graph.add_node(
            Node(record.application_id, NodeType.APPLICANT, {"name_present": bool(record.name)})
        )
        phone = normalise_phone(record.phone)
        if phone:
            graph.add_node(Node(f"phone:{phone}", NodeType.PHONE))
            graph.add_edge(
                Edge(record.application_id, f"phone:{phone}", EdgeType.SHARES_PHONE,
                     evidence="exact phone match")
            )
        account = normalise_account(record.account)
        if account:
            graph.add_node(Node(f"account:{account}", NodeType.BANK_ACCOUNT))
            graph.add_edge(
                Edge(record.application_id, f"account:{account}", EdgeType.SHARES_ACCOUNT,
                     evidence="exact account match")
            )
        if record.device_id:
            graph.add_node(Node(f"device:{record.device_id}", NodeType.DEVICE))
            graph.add_edge(
                Edge(record.application_id, f"device:{record.device_id}",
                     EdgeType.SHARES_DEVICE, evidence="exact device match")
            )
        if record.latitude is not None and record.longitude is not None:
            cell = geohash(record.latitude, record.longitude)
            graph.add_node(Node(f"geo:{cell}", NodeType.ADDRESS, {"geohash": cell}))
            graph.add_edge(
                Edge(record.application_id, f"geo:{cell}", EdgeType.SHARES_ADDRESS,
                     weight=1.0, evidence=f"geohash-{GEOHASH_PRECISION} cell")
            )
        if record.employer:
            employer = normalise_name(record.employer)
            graph.add_node(Node(f"employer:{employer}", NodeType.EMPLOYER))
            graph.add_edge(
                Edge(record.application_id, f"employer:{employer}",
                     EdgeType.SHARES_EMPLOYER, evidence="normalised employer name")
            )

    for match in matches:
        name_score = match.evidence.get("name", 0.0)
        if name_score >= name_threshold and not match.deterministic:
            graph.add_edge(
                Edge(
                    match.left,
                    match.right,
                    EdgeType.NAME_SIMILAR,
                    weight=name_score,
                    evidence=(
                        f"Jaro-Winkler {name_score:.3f} >= {name_threshold} "
                        f"({'ratified' if threshold_ratified else 'UNRATIFIED, LH-209'})"
                    ),
                )
            )
    return graph


def resolve(
    records: Sequence[ApplicationRecord],
    *,
    name_threshold: float,
    threshold_ratified: bool = False,
    threshold_provenance: str = "",
) -> tuple[EntityGraph, list[MatchScore]]:
    """Block, compare and build the graph in one pass."""
    pairs = candidate_pairs(records)
    by_id = {record.application_id: record for record in records}
    matches = [compare(by_id[left], by_id[right]) for left, right in sorted(pairs)]
    graph = build_graph(
        records,
        matches,
        name_threshold=name_threshold,
        threshold_ratified=threshold_ratified,
        threshold_provenance=threshold_provenance,
    )
    return graph, matches
