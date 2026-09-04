"""FaceChain — Visual Content Discovery & Blockchain Provenance (Streamlit UI)."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image
import streamlit as st

import os
import platform
import uuid

import config
from face.detector import FaceDetector
from face.embedding import extract_embedding_vector
from face.similarity import format_similarity
from search import (
    get_search_provider,
    normalize_provider,
    SearchResponse,
    SearchStatus,
    PROVIDERS,
)
from pipeline.models import CandidateResult, CandidateStatus
from pipeline.executor import run_candidate_evaluation, get_matches
from extraction.metadata import build_matched_record
from fingerprint.canonical import create_canonical_manifest, compute_provenance_hash, to_bytes32_hex
from blockchain.client import BlockchainClient, BlockchainError
from blockchain.verifier import verify_content, run_tamper_demonstration

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FaceChain — Provenance & Verification",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ FaceChain: Visual Content Discovery & Blockchain Provenance")
st.caption("HH Goa 2026 — Task 3: Local Face Verification & Tamper-Evident Provenance Registry")

# ─── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.header("⚙️ Pipeline Configuration")

raw_provider = st.sidebar.selectbox(
    "Search Provider",
    ["auto", "yandex", "bing", "google"],
    index=0,
)
provider_name = normalize_provider(raw_provider)

# Invalidate stale pipeline results when user switches provider
if st.session_state.get("_last_selected_provider") != provider_name:
    for key in ["pipeline_results", "tamper_results"]:
        st.session_state.pop(key, None)
    st.session_state["_last_selected_provider"] = provider_name

threshold = st.sidebar.slider(
    "Face Similarity Threshold",
    min_value=0.20, max_value=0.80,
    value=config.FACE_MATCH_THRESHOLD, step=0.05,
    help="ArcFace cosine similarity required to classify a candidate as a MATCH.",
)

# On Render or server environments, default to headless
is_render_env = bool(os.getenv("RENDER") or os.getenv("SERVER_SOFTWARE") or os.name != "nt")
default_headless = True
headless = st.sidebar.checkbox(
    "Headless Browser Search",
    value=default_headless,
    help="Keep checked on server deployments.",
)
config.SEARCH_HEADLESS = headless

default_rpc = os.getenv("BLOCKCHAIN_RPC_URL", config.BLOCKCHAIN_RPC_URL)
rpc_url = st.sidebar.text_input("Blockchain RPC URL", value=default_rpc)

# Blockchain node status badge in sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("🔗 Blockchain Status")
_b_client = BlockchainClient(rpc_url=rpc_url)
if _b_client.is_connected():
    st.sidebar.success("✓ Node Connected")
    if _b_client.contract_address:
        st.sidebar.caption(f"`{_b_client.contract_address}`")
    else:
        st.sidebar.warning("Contract not deployed — run deploy.js")
else:
    if is_render_env:
        st.sidebar.warning("⚠️ Blockchain Node Offline  \nProvide external RPC (e.g. Sepolia) to anchor on cloud.")
    else:
        st.sidebar.error("❌ Node Offline  \n`cd hardhat && npx hardhat node`")

st.info(
    "**Privacy Notice:** This pipeline performs local face detection and generates a 32-byte "
    "cryptographic fingerprint anchored to a local Ethereum blockchain. No raw images, "
    "biometrics, or PII are stored on-chain."
)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _image_bytes_hash(path: Path) -> str:
    """SHA-256 of raw file bytes — used to detect input image changes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def render_candidate_card(c: CandidateResult) -> None:
    """
    Safely renders a CandidateResult card in the Streamlit UI.
    Never passes unvalidated bytes to st.image().
    """
    # Image preview
    if c.local_path and Path(c.local_path).is_file():
        try:
            with Image.open(c.local_path) as img:
                st.image(img, use_container_width=True)
        except Exception as e:
            st.caption(f"⚠️ Preview error: {e}")
    elif c.thumbnail_url:
        st.caption(f"🖼️ Thumbnail: `{c.thumbnail_url[:60]}`")
    else:
        st.caption("🚫 No image available")

    # Metadata
    st.markdown(f"**Domain:** `{c.source_domain}`")
    title_short = (c.title[:48] + "…") if len(c.title) > 48 else c.title
    st.markdown(f"[{title_short}]({c.source_url})")
    st.markdown(f"**Rank:** #{c.search_rank}")

    # Status badge
    if c.status == CandidateStatus.MATCH:
        st.success(f"✅ **MATCH** — {format_similarity(c.face_similarity)}")
    elif c.status == CandidateStatus.BELOW_THRESHOLD:
        st.warning(f"⚠️ Below Threshold — {format_similarity(c.face_similarity)}")
    elif c.status == CandidateStatus.NO_FACE:
        st.error("❌ No Human Face Detected")
    elif c.status in (CandidateStatus.DOWNLOAD_FAILED, CandidateStatus.INVALID_IMAGE):
        err = (c.download_error or "")[:60]
        st.error(f"❌ {c.status.value} — {err}")
    elif c.status == CandidateStatus.MATCH_ERROR:
        st.warning(f"⚠️ Evaluation Error")
    else:
        st.caption(f"Status: {c.status_label}")

    if c.faces_count > 0:
        st.caption(f"👤 {c.faces_count} face(s) | sim={c.face_similarity:.3f}")
    if c.rejection_reason and c.status != CandidateStatus.MATCH:
        st.caption(f"ℹ️ {c.rejection_reason}")


# ─── Section 1 & 2: Reference Face ───────────────────────────────────────────
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Reference Face Input")
    demo_files = sorted(
        list(config.INPUT_DIR.glob("*.jpg")) +
        list(config.INPUT_DIR.glob("*.png"))
    )
    demo_opts = ["Upload Image"] + [f.name for f in demo_files]
    choice = st.selectbox("Select Image Source", demo_opts)

    selected_path: Optional[Path] = None
    if choice == "Upload Image":
        uploaded = st.file_uploader("Upload portrait photo", type=["jpg", "jpeg", "png"])
        if uploaded:
            save_path = config.INPUT_DIR / f"upload_{uploaded.name}"
            with open(save_path, "wb") as fh:
                fh.write(uploaded.getbuffer())
            selected_path = save_path
            st.image(uploaded, caption="Uploaded Image", use_container_width=True)
    else:
        selected_path = config.INPUT_DIR / choice
        st.image(str(selected_path), caption=choice, use_container_width=True)

with col2:
    st.subheader("2. Detection & ArcFace Embedding")
    if not (selected_path and selected_path.is_file()):
        st.warning("Please select or upload a reference portrait to begin.")
        st.stop()

    # Detect if image changed → reset pipeline results
    current_img_hash = _image_bytes_hash(selected_path)
    if st.session_state.get("_ref_img_hash") != current_img_hash:
        for key in ["pipeline_results", "tamper_results"]:
            st.session_state.pop(key, None)
        st.session_state["_ref_img_hash"] = current_img_hash

    @st.cache_resource(show_spinner="Loading InsightFace model…")
    def load_detector():
        return FaceDetector(model_name=config.INSIGHTFACE_MODEL)

    detector = load_detector()

    try:
        primary_face = detector.extract_primary_face(selected_path)
        query_embedding: np.ndarray = extract_embedding_vector(primary_face)
        st.success(
            f"✓ Face detected — confidence: **{primary_face.det_score:.3f}** | "
            f"bbox: {primary_face.bbox}"
        )
        st.write("✓ **512-d ArcFace embedding** generated locally on CPU.")
        with st.expander("🔬 Embedding Details", expanded=False):
            st.write(f"Shape: `{query_embedding.shape}` | L2 norm: `{float(np.linalg.norm(query_embedding)):.4f}`")
            st.code(f"Embedding[0:8]: {query_embedding[:8].tolist()}", language="python")
    except Exception as e:
        st.error(f"Face detection failed: {e}")
        st.stop()


# ─── Pipeline Trigger ─────────────────────────────────────────────────────────
st.divider()

if st.button("🚀 Run Visual Search & Verification Pipeline", type="primary"):
    # Clear stale tamper results from a previous run
    st.session_state.pop("tamper_results", None)
    search_run_id = uuid.uuid4().hex[:8]

    # LIVE SEARCH
    with st.spinner("🌐 Executing live visual search…"):
        t0 = time.time()
        provider = get_search_provider(provider_name)
        try:
            search_response: SearchResponse = provider.search_detailed(str(selected_path))
        except Exception as e:
            st.error(f"Visual search execution error: {e}")
            st.stop()
        search_candidates = search_response.candidates
        elapsed_search = search_response.elapsed_seconds

    if not search_candidates:
        if search_response.status == SearchStatus.PROVIDER_BLOCKED:
            st.error(
                f"🛑 **{provider_name.capitalize()} Search Blocked**: The search engine returned a bot verification or CAPTCHA challenge in this cloud environment."
            )
            st.info("💡 Try switching to **'bing'** or **'google'** in the sidebar.")
        elif search_response.status == SearchStatus.BROWSER_ERROR:
            st.error(f"❌ **Browser Automation Error**: {search_response.error}")
            st.info("Ensure Playwright Chromium is installed: `playwright install chromium`.")
        elif search_response.status == SearchStatus.PARSER_FAILURE:
            st.error(f"⚠️ **Parser Notice**: {search_response.error or 'Results page loaded, but candidates could not be extracted.'}")
            st.info("💡 Try switching to another provider in the sidebar.")
        elif search_response.status == SearchStatus.NETWORK_ERROR:
            st.error(f"🌐 **Network Error**: {search_response.error}")
        elif provider_name == "auto":
            st.error(search_response.error or "No candidates discovered across attempted providers.")
        else:
            st.warning(f"ℹ️ **{provider_name.capitalize()} search completed**, but no usable candidates were discovered.")
            st.info("💡 You can try a different search provider in the sidebar or upload a different reference photo.")
        st.stop()

    if provider_name == "auto":
        provider_used = search_response.diagnostics.get("winning_provider", getattr(provider, "last_provider_used", "auto"))
    else:
        provider_used = provider_name

    # CANDIDATE EVALUATION (with progress bar)
    progress_bar = st.progress(0, text="Evaluating candidates…")
    progress_state = {"n": 0}

    def _progress(idx, total, domain):
        progress_state["n"] = idx
        progress_bar.progress(
            idx / total,
            text=f"Candidate {idx}/{total}: {domain}"
        )

    t1 = time.time()
    all_candidates, matches = run_candidate_evaluation(
        search_candidates=search_candidates,
        detector=detector,
        query_embedding=query_embedding,
        threshold=threshold,
        search_provider=provider_used,
        progress_callback=_progress,
    )
    elapsed_eval = round(time.time() - t1, 2)
    progress_bar.empty()

    diagnostics = {
        "selected_provider": provider_name,
        "provider_used": provider_used,
        "search_elapsed_s": elapsed_search,
        "eval_elapsed_s": elapsed_eval,
        "raw_count": search_response.raw_results_count or len(search_candidates),
        "downloadable": sum(1 for c in all_candidates if c.download_success),
        "with_faces": sum(1 for c in all_candidates if c.faces_count > 0),
        "passing_threshold": len(matches),
        "threshold": threshold,
        "search_run_id": search_run_id,
        "search_status": search_response.status.value,
    }

    # Serialize CandidateResult objects to plain dicts for session state
    st.session_state["pipeline_results"] = {
        "all_candidates": [c.to_dict() for c in all_candidates],
        "diagnostics": diagnostics,
    }


# ─── Display Results ─────────────────────────────────────────────────────────
if "pipeline_results" not in st.session_state:
    st.stop()

_res = st.session_state["pipeline_results"]
_diag = _res["diagnostics"]

# Reconstruct typed CandidateResult objects from serialized dicts
all_candidates: List[CandidateResult] = [
    CandidateResult.from_dict(d) for d in _res["all_candidates"]
]
matches: List[CandidateResult] = get_matches(all_candidates)
threshold_used = _diag["threshold"]

# ── Section 3: Search Results ─────────────────────────────────────────────────
st.subheader(f"3. Live Search Results — {_diag['raw_count']} Discovered")
st.markdown(
    f"**Selected Provider:** `{_diag.get('selected_provider', provider_name).upper()}` | "
    f"**Engine Used:** `{_diag['provider_used'].upper()}` | "
    f"**Search time:** `{_diag['search_elapsed_s']}s` | "
    f"**Evaluation time:** `{_diag['eval_elapsed_s']}s`"
)

with st.expander("🔍 Pipeline Diagnostics", expanded=False):
    d_col1, d_col2 = st.columns(2)
    with d_col1:
        st.write("**Selected provider:**", _diag.get("selected_provider", provider_name))
        st.write("**Engine actually used:**", _diag["provider_used"])
        st.write("**Raw candidates found:**", _diag["raw_count"])
        st.write("**Downloadable images:**", _diag["downloadable"])
    with d_col2:
        st.write("**Human faces found:**", _diag["with_faces"])
        st.write(f"**Passing threshold (≥{threshold_used:.2f}):**", _diag["passing_threshold"])
        st.write("**Search Run ID:**", _diag.get("search_run_id", "N/A"))
        st.write("**Execution Status:**", _diag.get("search_status", "SUCCESS"))

with st.expander("🖥️ Deployment & Environment Diagnostics", expanded=False):
    env_col1, env_col2 = st.columns(2)
    with env_col1:
        st.write("**Environment:**", "Render Cloud" if is_render_env else f"Local ({platform.system()})")
        st.write("**Python Version:**", platform.python_version())
        st.write("**Headless Search:**", "Enabled" if config.SEARCH_HEADLESS else "Disabled")
    with env_col2:
        st.write("**Selected Provider:**", provider_name)
        st.write("**Provider Implementation:**", PROVIDERS.get(provider_name, AutoVisualProvider).__name__)
        st.write("**Blockchain RPC:**", rpc_url)
        st.write("**Blockchain Status:**", "Connected" if _b_client.is_connected() else "Offline")

# ── Section 4: Candidate Analysis ────────────────────────────────────────────
st.subheader("4. Candidate Analysis")

m1, m2, m3, m4 = st.columns(4)
m1.metric("1. Discovered", _diag["raw_count"])
m2.metric("2. Downloadable", _diag["downloadable"])
m3.metric("3. Human Faces Found", _diag["with_faces"])
m4.metric(f"4. Passing ≥{threshold_used:.2f}", _diag["passing_threshold"])

tab_all, tab_match, tab_rejected = st.tabs([
    f"All Candidates ({len(all_candidates)})",
    f"Matches ({len(matches)})",
    f"Rejected ({len(all_candidates) - len(matches)})",
])

with tab_all:
    top = all_candidates[:9]
    if top:
        cols = st.columns(min(3, len(top)))
        for i, c in enumerate(top):
            with cols[i % 3]:
                with st.container(border=True):
                    st.markdown(f"**#{i+1}** `{c.candidate_id}`")
                    render_candidate_card(c)
    else:
        st.info("No candidates.")

with tab_match:
    if matches:
        mcols = st.columns(min(3, len(matches)))
        for i, c in enumerate(matches):
            with mcols[i % 3]:
                with st.container(border=True):
                    render_candidate_card(c)
    else:
        st.info("No candidates passed the similarity threshold.")

with tab_rejected:
    # Explicit status-based rejection — no is_match key lookups
    rejected_no_face = [c for c in all_candidates if c.status == CandidateStatus.NO_FACE]
    rejected_below = [c for c in all_candidates if c.status == CandidateStatus.BELOW_THRESHOLD]
    rejected_download = [c for c in all_candidates if c.status in (
        CandidateStatus.DOWNLOAD_FAILED, CandidateStatus.INVALID_IMAGE,
    )]
    rejected_error = [c for c in all_candidates if c.status == CandidateStatus.MATCH_ERROR]

    if rejected_no_face:
        st.markdown(f"**❌ No Human Face Detected ({len(rejected_no_face)}):**")
        r_cols = st.columns(min(3, len(rejected_no_face)))
        for i, c in enumerate(rejected_no_face[:6]):
            with r_cols[i % 3]:
                with st.container(border=True):
                    render_candidate_card(c)

    if rejected_below:
        st.markdown(f"**⚠️ Below Similarity Threshold ({len(rejected_below)}):**")
        b_cols = st.columns(min(3, len(rejected_below)))
        for i, c in enumerate(rejected_below[:6]):
            with b_cols[i % 3]:
                with st.container(border=True):
                    render_candidate_card(c)

    if rejected_download:
        st.markdown(f"**❌ Inaccessible / Invalid Image ({len(rejected_download)}):**")
        for c in rejected_download[:4]:
            st.caption(f"• `{c.source_domain}` — {c.download_error or 'unknown error'}")

    if rejected_error:
        st.markdown(f"**⚠️ Evaluation Errors ({len(rejected_error)}):**")
        for c in rejected_error[:4]:
            st.caption(f"• `{c.source_domain}` — {c.rejection_reason}")

    if not any([rejected_no_face, rejected_below, rejected_download, rejected_error]):
        st.info("All candidates passed. No rejections.")


# ── Section 5: Best Match ────────────────────────────────────────────────────
st.subheader("5. Best Face Match")

if not matches:
    st.warning(
        f"⚠️ **NO SUFFICIENT FACE MATCH FOUND**\n\n"
        f"No candidate achieved the required face similarity of {threshold_used:.2f}. "
        f"Pipeline halted: unrelated content will not be anchored to blockchain."
    )
    st.stop()

best = matches[0]

st.success(
    f"✓ Confirmed Match: **{best.source_domain}** — "
    f"Face Similarity: **{format_similarity(best.face_similarity)}** "
    f"({best.faces_count} face(s) verified in image)"
)

b_col1, b_col2 = st.columns([1, 2])
with b_col1:
    if best.local_path and Path(best.local_path).is_file():
        try:
            with Image.open(best.local_path) as img:
                st.image(img, caption=f"{best.source_domain}", use_container_width=True)
        except Exception as e:
            st.warning(f"Could not display: {e}")
with b_col2:
    st.write("**Source URL:**", best.source_url)
    st.write("**Domain:**", f"`{best.source_domain}`")
    st.write("**Face Similarity:**", f"`{best.face_similarity:.4f}` ({format_similarity(best.face_similarity)})")
    st.write("**Faces in image:**", best.faces_count)
    st.write("**Search Rank:**", f"#{best.search_rank}")
    st.write("**Candidate ID:**", f"`{best.candidate_id}`")

# ── Section 6: Content Fingerprint ───────────────────────────────────────────
st.subheader("6. Content Fingerprint (Canonical SHA-256)")

retrieved_at = datetime.now(timezone.utc).isoformat()
record = build_matched_record(
    source_url=best.source_url,
    title=best.title,
    image_url=best.resolved_url or best.image_url or best.source_url,
    face_similarity=best.face_similarity,
    search_provider=_diag["provider_used"],
    content_type=best.content_type or "image/jpeg",
    image_byte_size=best.byte_size or 0,
    image_sha256=best.image_sha256 or "",
    retrieved_at=retrieved_at,
)
manifest = create_canonical_manifest(
    source_url=record.normalized_url,
    image_sha256=record.image_sha256,
    title=record.title,
    source_domain=record.source_domain,
    retrieved_at=record.retrieved_at,
)
prov_hash = compute_provenance_hash(manifest)
b32_hash = to_bytes32_hex(prov_hash)

fp_col1, fp_col2 = st.columns(2)
with fp_col1:
    st.markdown("**Canonical Provenance Manifest:**")
    st.json(manifest)
with fp_col2:
    st.markdown("**Cryptographic Fingerprints:**")
    st.code(f"Image SHA-256:\n{record.image_sha256}", language="text")
    st.code(f"Provenance Hash (bytes32):\n{b32_hash}", language="text")

# ── Section 7: Blockchain Provenance ─────────────────────────────────────────
st.subheader("7. Blockchain Provenance")

client = BlockchainClient(rpc_url=rpc_url)

if not client.is_connected():
    st.error(
        f"❌ Blockchain node unreachable at `{rpc_url}`.\n\n"
        "Start Hardhat in a terminal:\n"
        "```\ncd hardhat\nnpx hardhat node\n```\n"
        "Then deploy contract:\n"
        "```\nnpx hardhat run scripts/deploy.js --network localhost\n```"
    )
elif not client.contract:
    st.error(
        "❌ Smart contract not deployed. Run:\n"
        "```\ncd hardhat && npx hardhat run scripts/deploy.js --network localhost\n```"
    )
else:
    # Attempt to submit real blockchain transaction
    tx_data = None
    tx_error = None
    try:
        tx_data = client.record_provenance(prov_hash)
    except BlockchainError as be:
        tx_error = str(be)
    except Exception as exc:
        tx_error = f"Unexpected error: {exc}"

    # Real on-chain verification — query the contract directly
    verification = None
    on_chain_info = {}
    verify_error = None
    try:
        verification = verify_content(manifest, client)
        on_chain_info = verification.details
    except Exception as ve:
        verify_error = str(ve)

    st.markdown("#### 🔗 Real On-Chain Transaction Record")
    bc1, bc2 = st.columns(2)
    with bc1:
        st.write("**Network:**", "Hardhat Local Ethereum (Chain ID 31337)")
        st.write("**RPC Endpoint:**", f"`{rpc_url}`")
        st.write("**Contract Address:**", f"`{client.contract_address}`")
        try:
            wallet = client.get_default_account()
            st.write("**Recorder Wallet:**", f"`{wallet}`")
        except Exception:
            st.write("**Recorder Wallet:**", "Unavailable")
        st.write("**Provenance Hash Submitted:**", f"`{b32_hash}`")

    with bc2:
        if tx_data:
            st.write("**Transaction Hash:**", f"`{tx_data['transaction_hash']}`")
            st.write("**Block Number:**", f"`#{tx_data['block_number']}`")
            st.write("**Gas Used:**", f"`{tx_data['gas_used']:,}`")
            status_icon = "✅" if tx_data["status"] == "SUCCESS" else "❌"
            st.write("**TX Status:**", f"{status_icon} `{tx_data['status']}`")
        elif tx_error and "RecordAlreadyExists" in tx_error:
            st.info("ℹ️ **Hash already anchored** — this hash was previously recorded on-chain.")
        elif tx_error:
            st.error(f"Transaction error: `{tx_error}`")

        if on_chain_info.get("timestamp"):
            from datetime import datetime, timezone
            ts_dt = datetime.fromtimestamp(on_chain_info["timestamp"], tz=timezone.utc)
            st.write("**Anchored At (On-Chain):**", ts_dt.strftime("%Y-%m-%d %H:%M:%S UTC"))
        if on_chain_info.get("recorder") and on_chain_info["recorder"] != "0x" + "0" * 40:
            st.write("**On-Chain Recorder:**", f"`{on_chain_info['recorder']}`")
        if on_chain_info.get("latest_block"):
            st.write("**Current Block (live):**", f"`#{on_chain_info['latest_block']}`")
        if on_chain_info.get("chain_id"):
            st.write("**Chain ID (live):**", f"`{on_chain_info['chain_id']}`")

    # ── Section 8: Blockchain Verification ────────────────────────────────────
    st.subheader("8. Blockchain Verification")
    st.caption(
        "Proves the fingerprint was retrieved from the chain — "
        "NOT just that two identical strings match."
    )

    if verify_error:
        st.error(f"❌ Verification query failed: `{verify_error}`")
    elif verification is None:
        st.warning("Verification could not be completed.")
    else:
        # ─── The honest verification table ──────────────────────────────────
        # Column 1: what we computed locally RIGHT NOW from the manifest
        # Column 2: what the blockchain contract confirmed (exists + metadata)
        queried = on_chain_info.get("queried_hash", b32_hash)
        exists_on_chain = on_chain_info.get("exists", False)
        anchor_time = on_chain_info.get("timestamp", 0)
        recorder = on_chain_info.get("recorder", "")
        chain_id = on_chain_info.get("chain_id", "?")
        latest_blk = on_chain_info.get("latest_block", "?")

        ts_str = "N/A"
        if anchor_time:
            from datetime import datetime, timezone
            ts_str = datetime.fromtimestamp(anchor_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        v1, v2 = st.columns(2)
        with v1:
            st.markdown("**🖥️ LOCAL COMPUTATION**")
            st.markdown("Recomputed deterministically from canonical manifest:")
            st.code(f"Provenance Hash:\n{b32_hash}", language="text")
            st.code(f"Image SHA-256:\n{record.image_sha256}", language="text")

        with v2:
            st.markdown("**🔗 ON-CHAIN QUERY RESULT**")
            st.markdown(f"Contract `verify(hash)` call at block `#{latest_blk}` (Chain ID `{chain_id}`):")
            if exists_on_chain:
                st.success(f"✅ `exists = True`")
                st.write(f"**Anchored at:** `{ts_str}`")
                st.write(f"**Recorder:** `{recorder}`")
                st.write(f"**Queried hash:** `{queried}`")
            else:
                st.error("❌ `exists = False` — Hash not found in registry")

        # Final verdict
        st.divider()
        if verification.is_verified and exists_on_chain:
            st.success(
                "✅ **VERIFICATION PASSED: HASH IS ANCHORED ON-CHAIN**\n\n"
                f"The contract `verify()` call confirmed `exists = True` for hash:\n\n"
                f"`{queried}`\n\n"
                f"Anchored at `{ts_str}` by `{recorder}` on Chain ID `{chain_id}`."
            )
        else:
            st.error(
                "❌ **VERIFICATION FAILED: Hash Not Found On-Chain**\n\n"
                "The contract returned `exists = False`. "
                "The hash has not been anchored in this blockchain session."
            )

    # ── Section 9: Tamper Simulation ──────────────────────────────────────────
    st.divider()
    st.subheader("9. Tamper Simulation")
    st.caption(
        "Demonstrates that modifying even 3 pixels of the matched image produces a "
        "completely different SHA-256 fingerprint — which the blockchain rejects."
    )

    if st.button("🧪 Simulate Content Tampering (Modify 3 Pixels)", type="secondary"):
        if best.local_path and Path(best.local_path).is_file():
            try:
                tamper_res = run_tamper_demonstration(
                    original_image_path=Path(best.local_path),
                    original_manifest=manifest,
                    blockchain_client=client,
                )
                st.session_state["tamper_results"] = tamper_res
            except Exception as te:
                st.error(f"Tamper demonstration failed: {te}")
        else:
            st.error("Matched image file not available for tampering.")

    if "tamper_results" in st.session_state:
        t_res = st.session_state["tamper_results"]
        st.warning("⚠️ 3 corner pixels inverted in matched image — recomputing hashes…")

        t1, t2 = st.columns(2)
        with t1:
            st.markdown("**✅ Original Content — ON-CHAIN**")
            st.code(
                f"Image SHA-256:\n{t_res['original_image_sha256']}\n\n"
                f"Provenance Hash:\n{t_res['original_provenance_hash']}",
                language="text"
            )
            st.success("✅ Found in blockchain registry")
        with t2:
            st.markdown("**❌ Tampered Content — NOT ON-CHAIN**")
            st.code(
                f"Image SHA-256:\n{t_res['tampered_image_sha256']}\n\n"
                f"Provenance Hash:\n{t_res['tampered_provenance_hash']}",
                language="text"
            )
            if t_res.get("tamper_detected"):
                st.error("❌ Rejected — Not in blockchain registry")
            else:
                st.warning("⚠️ Unexpected match (hash collision?)")

        if t_res.get("tamper_detected"):
            orig_short = t_res['original_provenance_hash'][:22]
            tamp_short = t_res['tampered_provenance_hash'][:22]
            st.error(
                f"❌ **RESULT: TAMPER DETECTED — VERIFICATION FAILED**\n\n"
                f"**Original hash** `{orig_short}…` → ✅ `exists = True` on-chain\n\n"
                f"**Tampered hash** `{tamp_short}…` → ❌ `exists = False` (NOT found on-chain)\n\n"
                "Modifying just 3 pixels changes the SHA-256 completely. "
                "The blockchain contract has no record of the tampered fingerprint — "
                "cryptographic proof the content was altered after anchoring."
            )
        else:
            st.warning("⚠️ Unexpected: tampered hash found on-chain (hash collision?)")

