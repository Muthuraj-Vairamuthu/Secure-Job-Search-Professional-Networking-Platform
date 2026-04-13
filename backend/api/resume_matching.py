import os
import re
import zipfile
from io import BytesIO

try:
    import fitz as _fitz
    _PYMUPDF_AVAILABLE = True
except ImportError:
    _PYMUPDF_AVAILABLE = False


KNOWN_SKILLS = [
    "python", "java", "javascript", "typescript", "react", "node.js", "node",
    "flask", "django", "fastapi", "sql", "sqlite", "mysql", "postgresql",
    "mongodb", "html", "css", "aws", "docker", "kubernetes", "git", "linux",
    "cybersecurity", "network security", "information security", "api",
    "rest", "graphql", "machine learning", "data analysis", "pandas", "numpy",
    "c", "c++", "c#", "php", "ruby", "go", "devops", "testing"
]


def extract_resume_text(file_bytes, filename):
    ext = os.path.splitext(filename.lower())[1]
    text = ""

    if ext == ".pdf" and _PYMUPDF_AVAILABLE:
        try:
            doc = _fitz.open(stream=file_bytes, filetype="pdf")
            text = "\n".join(page.get_text("text") for page in doc)
            doc.close()
        except Exception:
            text = ""
    elif ext == ".docx":
        text = _extract_docx_text(file_bytes)
    elif ext == ".doc":
        text = _decode_fallback(file_bytes)
    else:
        text = _decode_fallback(file_bytes)

    if not text.strip():
        text = _decode_fallback(file_bytes)

    return _normalize_whitespace(text)


def extract_skills_from_text(text):
    lowered = text.lower()
    found = []

    for skill in KNOWN_SKILLS:
        pattern = r'(?<!\w)' + re.escape(skill.lower()) + r'(?!\w)'
        if re.search(pattern, lowered):
            found.append(skill)

    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9\+#\.-]{1,24}", lowered))
    for token in tokens:
        if token in {"aws", "sql", "api", "rest", "react", "python", "java", "docker", "linux"}:
            found.append(token)

    return sorted(set(found))


def compute_job_match(job_title, job_description, job_skills, resume_text, resume_skills):
    requested_skills = _extract_requested_skills(job_title, job_description, job_skills)
    resume_skill_set = {skill.lower() for skill in resume_skills}
    resume_text_lower = (resume_text or "").lower()

    matched = []
    missing = []
    for skill in requested_skills:
        skill_lower = skill.lower()
        if skill_lower in resume_skill_set or skill_lower in resume_text_lower:
            matched.append(skill)
        else:
            missing.append(skill)

    if requested_skills:
        score = round((len(matched) / len(requested_skills)) * 100)
    else:
        generic_hits = 0
        title_keywords = _keyword_tokens(job_title) | _keyword_tokens(job_description)
        for keyword in title_keywords:
            if keyword in resume_text_lower:
                generic_hits += 1
        denominator = max(len(title_keywords), 1)
        score = round((generic_hits / denominator) * 100)

    return {
        "score": score,
        "requested_skills": requested_skills,
        "matched_skills": matched[:8],
        "missing_skills": missing[:8],
        "resume_skills_detected": resume_skills[:12]
    }


def _extract_requested_skills(job_title, job_description, job_skills):
    combined = ", ".join(filter(None, [job_skills, job_title, job_description]))
    lowered = combined.lower()
    found = []

    for skill in KNOWN_SKILLS:
        pattern = r'(?<!\w)' + re.escape(skill.lower()) + r'(?!\w)'
        if re.search(pattern, lowered):
            found.append(skill)

    if job_skills:
        for piece in job_skills.split(','):
            clean = _normalize_whitespace(piece).strip(" -")
            if clean:
                found.append(clean.lower())

    return sorted(set(found))


def _extract_docx_text(file_bytes):
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as docx_zip:
            xml = docx_zip.read("word/document.xml").decode("utf-8", errors="ignore")
            text = re.sub(r"</w:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", " ", text)
            return _normalize_whitespace(text)
    except Exception:
        return ""


def _decode_fallback(file_bytes):
    for encoding in ("utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _normalize_whitespace(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _keyword_tokens(text):
    return {
        token for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\+#\.-]{2,24}", (text or "").lower())
        if token not in {"the", "and", "for", "with", "from", "that", "this", "your", "you", "our"}
    }
