"""Pinned local LaTeX templates and isolated, reproducible report build attempts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

CATALOGUE = "https://latex.sharif.edu/templates/63a98879ab56c300a159ea1e"
RECIPE_VERSION = "1"
FONT_SOURCE = {
    "source_url": "https://fontlibrary.org/assets/downloads/xb-niloofar/443e92a9b431497a28b6d9e7d1384c40/xb-niloofar.zip",
    "sha256": "3575302c74b55e6992c0a64b7d4a193c0dc8a95fe8ea62d06959ce4586bf90a6",
}
TEMPLATES = {
    "sharif-exercise": {
        "name": "تمرین بدون جلد",
        "purpose": "پاسخ سؤال‌های تکلیف با سربرگ کوتاه",
        "upstream_id": "639854882581e80097d08105",
        "sha256": "bf662c64c76b226ae35c0d9f3aae992bd5cb717e6ffd6046c642a1afc67301c0",
    },
    "sharif-exercise-cover": {
        "name": "تمرین با جلد",
        "purpose": "پاسخ تکلیف با صفحهٔ عنوان مستقل",
        "upstream_id": "6398523d2581e80097d08066",
        "sha256": "821f758c7998830ed98c1ba2be5f736a014653d6df1d13b99026aec6bb81aa13",
    },
    "sharif-project-report": {
        "name": "گزارش پروژه",
        "purpose": "گزارش پروژه یا آزمایشگاه با بخش‌ها و شکل‌ها",
        "upstream_id": "63b3420c78d656009cf525c7",
        "sha256": "f408d98d87c8f22a4604debc926eee727a97e650a4f7f6f0b3980c0ea1a30ca9",
    },
}
_MAX_ARCHIVE = 20 * 1024 * 1024
_MAX_EXTRACTED = 80 * 1024 * 1024
_FONT = (
    r"[Renderer=OpenType,Script=Arabic,Path=fonts/,BoldFont={XB NiloofarBd.ttf},"
    r"ItalicFont={XB NiloofarIt.ttf},BoldItalicFont={XB NiloofarBdIt.ttf}]"
    r"{XB Niloofar.ttf}"
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _download(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        payload = response.read(_MAX_ARCHIVE + 1)
    if len(payload) > _MAX_ARCHIVE:
        raise ValueError("حجم بستهٔ قالب بیش از حد مجاز است")
    return payload


def _archive_files(payload: bytes) -> dict[str, bytes]:
    """Validate all entries before any file is written, including Windows paths."""
    files = {}
    names = set()
    total = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for item in archive.infolist():
            name = item.orig_filename
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (
                path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or any(ord(char) < 32 for char in name)
                or stat.S_ISLNK(mode) or not path.parts
                or any(part.rstrip(". ") != part for part in path.parts)
                or any(part.split(".")[0].upper() in {
                    "CON", "PRN", "AUX", "NUL", *{"COM" + str(i) for i in range(10)},
                    *{"LPT" + str(i) for i in range(10)},
                } for part in path.parts)
            ):
                raise ValueError("مسیر ناامن در بستهٔ قالب")
            key = path.as_posix().casefold()
            if key in names:
                raise ValueError("مسیر تکراری در بستهٔ قالب")
            names.add(key)
            total += item.file_size
            if total > _MAX_EXTRACTED:
                raise ValueError("حجم فایل‌های قالب بیش از حد مجاز است")
            if not item.is_dir():
                files[path.as_posix()] = archive.read(item)
    return files


def _obtain(template_id: str, root: Path) -> dict[str, bytes]:
    return _obtain_spec(template_id, TEMPLATES[template_id], root)


def _obtain_spec(template_id: str, spec: dict, root: Path) -> dict[str, bytes]:
    path = root / template_id / (spec["sha256"] + ".zip")
    if path.exists():
        payload = path.read_bytes()
    else:
        payload = _download(_source_url(spec))
        if _digest(payload) != spec["sha256"]:
            raise ValueError("سورس سایت تغییر کرده است؛ نسخهٔ تازه باید جداگانه بررسی شود")
        _archive_files(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    if _digest(payload) != spec["sha256"]:
        raise ValueError("نسخهٔ محلی قالب با اثر انگشت ثبت‌شده سازگار نیست")
    return _archive_files(payload)


def _source_url(spec: dict) -> str:
    if "source_url" in spec:
        return spec["source_url"]
    return "https://latex.sharif.edu/latex/templates/{}/zip".format(spec["upstream_id"])


def catalogue(root: Path) -> list[dict]:
    """List choices without network access, creating no local state."""
    return [
        {"id": key, **spec, "source_url": _source_url(spec), "catalogue_url": CATALOGUE,
         "recipe_version": RECIPE_VERSION, "language": "fa", "engine": "xelatex",
         "cached": (root / key / (spec["sha256"] + ".zip")).is_file(),
         "license": "not_declared_by_upstream"}
        for key, spec in TEMPLATES.items()
    ]


def _escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
        "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "\n": " ", "\r": " ",
    }
    return "".join(replacements.get(char, char) for char in value)


def _metadata(value: dict) -> dict:
    allowed = {"title", "english_title", "authors", "course", "term", "professor",
               "department", "university", "date"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("فیلدهای مشخصات گزارش نامعتبرند")
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        raise ValueError("عنوان واقعی گزارش لازم است")
    if any(not isinstance(v, str) for k, v in value.items() if k != "authors"):
        raise ValueError("مشخصات گزارش باید متن باشند")
    authors = value.get("authors", [])
    if not isinstance(authors, list) or any(not isinstance(a, str) or not a.strip() for a in authors):
        raise ValueError("نویسندگان باید فهرستی از نام‌ها باشند")
    return {**{key: _escape(value.get(key, "")) for key in allowed - {"authors"}},
            "authors": r"\\".join(_escape(author) for author in authors)}


def _commands(values: dict) -> str:
    return "\n".join(r"\newcommand{{\{}}}{{{}}}".format(key, value) for key, value in values.items()) + "\n"


def _optional_block(source: str, marker: str, field: str) -> str:
    """Hide an optional label and its field when no factual metadata was supplied."""
    pattern = re.escape(marker) + r".*?" + re.escape(field) + r"\}\}"
    return re.sub(pattern, lambda m: r"\ifx" + field + r"\empty\else " + m[0] + r"\fi", source, flags=re.S)


def _adapt(files: dict[str, bytes], template_id: str, meta: dict, fonts: dict[str, bytes]) -> dict[str, bytes]:
    """Keep upstream layout while replacing sample content and repairing dependencies."""
    result = dict(files)
    result.update({"fonts/" + PurePosixPath(name).name: data for name, data in fonts.items()
                   if name.endswith((".ttf", ".txt"))})
    if template_id.startswith("sharif-exercise"):
        text = files["main.tex"].decode("utf-8-sig")
        text = text.split("• پرسش")[0]
        text = text.replace(r"\usepackage{xepersian}",
                            r"\usepackage[dvipsnames]{xcolor}" + "\n" + r"\usepackage{amsmath,amssymb}" + "\n" + r"\usepackage{xepersian}")
        text = text.replace(r"\settextfont{XB Niloofar}", r"\settextfont" + _FONT)
        values = {"class": meta["course"], "term": meta["term"],
                  "college": meta["department"], "prof": meta["professor"]}
        for key, value in values.items():
            replacement = "\\newcommand{\\" + key + "}{" + value + "}"
            text = re.sub(r"\\newcommand\{\\" + key + r"\}\{[^\n]*\}",
                          lambda _, replacement=replacement: replacement, text)
        text = text.replace("تمرین سری پنجم", meta["title"])
        text = text.replace(r"\begin{document}", r"\printanswers" + "\n" +
                            r"\renewcommand{\solutiontitle}{\noindent\textbf{پاسخ:}\enspace}" + "\n" + r"\begin{document}")
        if template_id == "sharif-exercise":
            text += "\n" + r"\noindent " + meta["authors"] + "\n\n"
        result["main.tex"] = (text + "\n\\input{content.tex}\n\\end{document}\n").encode("utf-8")
        if template_id == "sharif-exercise-cover":
            result["info.tex"] = _commands({
                "ThesisType": "", "ThesisDegree": "", "ThesisMajor": "",
                "ThesisTitle": meta["title"], "ThesisAuthor": meta["authors"],
                "ThesisSupervisor": meta["professor"], "ThesisDate": meta["date"],
                "ThesisDepartment": meta["department"], "ThesisUniversity": meta["university"],
                "EnglishThesisTitle": meta["english_title"],
            }).encode("utf-8")
            cover = files["cover-page.tex"].decode("utf-8-sig")
            cover = _optional_block(cover, "{استاد راهنما}", r"\ThesisSupervisor")
            cover = _optional_block(cover, "{نگارش}", r"\ThesisAuthor")
            result["cover-page.tex"] = cover.encode("utf-8")
    else:
        main = files["Seminar.tex"].decode("utf-8-sig")
        main = main.replace(r"\include{chapters/context}", r"\input{content.tex}")
        main = main.replace(r"\include{bibs/bibs}", "")
        main = main.replace(r"\begin{appendix}", "").replace(r"\include{chapters/appendix}", "").replace(r"\end{appendix}", "")
        result["main.tex"] = main.encode("utf-8")
        # Sample prose, bibliography and appendix are never part of a prepared report.
        for name in ("Seminar.tex", "chapters/context.tex", "chapters/appendix.tex", "bibs/bibs.tex"):
            result.pop(name, None)
        result["front/info.tex"] = _commands({
            "ProjectReportType": "", "StudentDegree": "", "CourseMajor": "",
            "CourseReportTitle": meta["title"], "GroupeMembers": meta["authors"],
            "CourseName": meta["course"], "courseSemester": meta["term"],
            "CourseProfessor": meta["professor"], "Department": meta["department"],
            "University": meta["university"], "EnglishCourseTitle": meta["english_title"],
        }).encode("utf-8")
        common = files["styles/common.tex"].decode("utf-8-sig")
        common = common.replace("[localise=on,extrafootnotefeatures]", "[extrafootnotefeatures]")
        common = common.replace(r"\usepackage[noend]{algpseudocode}", "")
        common = common.replace(r"\usepackage[extrafootnotefeatures]{xepersian}",
                                r"\usepackage[noend]{algpseudocode}" + "\n" + r"\usepackage{listings}" + "\n" +
                                r"\usepackage[extrafootnotefeatures]{xepersian}")
        for name in ("برچسب", "حذف"):
            command = "\\renewcommand{\\" + name + "}"
            common = common.replace(command, "\\providecommand{\\" + name + "}{}\n" + command)
        common = common.replace(r"\settextfont[Scale=1.166666666666666]{XBNiloofar}",
                                r"\settextfont[Scale=1.166666666666666," + _FONT[1:])
        common = common.replace(r"\setdigitfont{Yas}", r"\setdigitfont" + _FONT)
        common = common.replace("[chapter]", "[section]")
        common = common.replace(r"\renewcommand{\bibname}",
                                r"\providecommand{\bibname}{}" + "\n" + r"\renewcommand{\bibname}")
        common = common.replace(r"\begin{latin}\settextfont[Scale=1.0]{Times New Roman}", r"\begin{latin}\rmfamily")
        # Keep normal content portable; PSTricks remains opt-in for assignments that need it.
        common = common.replace(r"\usepackage[usenames,dvipsnames]{pstricks}", r"\usepackage[dvipsnames]{xcolor}")
        common = common.replace(r"\renewcommand{\psscalebox}[1]{}", r"\providecommand{\psscalebox}[1]{}")
        common = common.replace(r"\setlength{\intextsep}{0pt}", r"\setlength{\intextsep}{\baselineskip}")
        result["styles/common.tex"] = common.encode("utf-8")
        if "styles/alg-fa.tex" in result:
            alg = result["styles/alg-fa.tex"].decode("utf-8-sig")
            # Legacy localisation treated ZWNJ as a control-word letter; modern XePersian does not.
            alg = alg.replace("\u200c", "")
            alg = alg.replace(r"\renewcommand{\ورودی}", r"\providecommand{\ورودی}{}" + "\n" + r"\renewcommand{\ورودی}")
            result["styles/alg-fa.tex"] = alg.encode("utf-8")
        title = files["front/template/title.tex"].decode("utf-8-sig")
        title = _optional_block(title, "{اعضای گروه}", r"\GroupeMembers")
        title = _optional_block(title, "{نام درس}", r"\CourseName")
        title = _optional_block(title, "{نام استاد درس}", r"\CourseProfessor")
        result["front/template/title.tex"] = title.encode("utf-8")
    result["content.tex"] = b""
    result["BUILD.md"] = (
        "# Building this report\n\nRun from this folder with XeLaTeX and its required packages installed.\n"
        "Fonts and local assets are included. Upstream templates: " + CATALOGUE + "\n\n"
        "xelatex -no-shell-escape -interaction=nonstopmode -halt-on-error main.tex\n\n"
        "If main.aux contains bibliography data, run bibtex main, then XeLaTeX twice.\n"
        "Otherwise run XeLaTeX a second time to resolve references and page counts.\n"
        "See report.json for upstream identity and local recipe version.\n"
    ).encode("utf-8")
    return result


def prepare(template_id: str, project: Path, metadata: dict, reason: str, root: Path) -> dict:
    """Create a fresh editable project from verified cached upstream bytes."""
    try:
        if not isinstance(template_id, str) or template_id not in TEMPLATES or not isinstance(reason, str) or not reason.strip():
            raise ValueError("قالب شناخته‌شده و دلیل انتخاب لازم‌اند")
        meta = _metadata(metadata)
        files = _obtain(template_id, root)
        fonts = _obtain_spec("xb-niloofar", FONT_SOURCE, root)
        adapted = _adapt(files, template_id, meta, fonts)
        manifest = {
            "template_id": template_id, "template_sha256": TEMPLATES[template_id]["sha256"],
            "recipe_version": RECIPE_VERSION, "selection_reason": reason.strip(),
            "catalogue_url": CATALOGUE, "source_url": _source_url(TEMPLATES[template_id]),
            "font_source_sha256": FONT_SOURCE["sha256"],
            "font_source_url": FONT_SOURCE["source_url"], "engine": "xelatex",
            "attribution": "Zeinab Seifoori; TexReady Group catalogue",
            "upstream_license": "not_declared_by_upstream", "metadata": metadata,
        }
        project.mkdir(parents=True, exist_ok=False)
        for name, payload in adapted.items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        _json(project / "report.json", manifest)
        return {"status": "ok", "project": str(project.resolve()), "report": {
            **manifest, "status": "prepared", "project": str(project.resolve()),
        }, "content_path": str((project / "content.tex").resolve())}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        return {"status": "needs_completion", "message": str(exc)}


def build(project: Path, attempts: Path, *, timeout: int = 120) -> dict:
    """Freeze every input and retain the source bundle on success or failure."""
    try:
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise ValueError("مهلت هر ابزار ساخت باید عدد صحیح مثبت باشد")
        if not (project / "content.tex").read_text(encoding="utf-8").strip():
            raise ValueError("متن پاسخ هنوز در content.tex نوشته نشده است")
        manifest = json.loads((project / "report.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not all(
            isinstance(manifest.get(key), str) and manifest[key].strip()
            for key in ("template_id", "template_sha256", "recipe_version", "selection_reason")
        ):
            raise ValueError("مشخصات نسخهٔ قالب در پروژه نامعتبر است")
        attempt = attempts / uuid.uuid4().hex
        source = attempt / "source"
        source.mkdir(parents=True)
        inputs = {}
        for path in sorted(project.rglob("*")):
            if path.is_symlink():
                raise ValueError("پیوند فایل در سورس گزارش مجاز نیست")
            if path.is_file():
                relative = path.relative_to(project)
                payload = path.read_bytes()
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                inputs[relative.as_posix()] = _digest(payload)
        source_digest = _digest(json.dumps(inputs, sort_keys=True).encode("utf-8"))
        bundle = attempt / "source.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in inputs:
                archive.write(source / name, name)
        compiled = attempt / "compiled"
        compiled.mkdir()
        log_path = attempt / "build.log"
        engine = shutil.which("xelatex")
        report = {**manifest, "project": str(project.resolve()), "status": "failed",
                  "source_digest": source_digest, "source_sha256": _digest(bundle.read_bytes()),
                  "source_path": str(bundle.resolve()), "log_path": str(log_path.resolve())}
        log = []

        def run(command: list[str], cwd: Path) -> None:
            result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
            output = result.stdout.decode("utf-8", errors="replace")
            log.append(output)
            log_path.write_text("\n".join(log), encoding="utf-8")
            if result.returncode:
                raise ValueError(output[-5000:] or "اجرای ابزار ساخت ناموفق بود")

        try:
            if not engine:
                raise ValueError("XeLaTeX پیدا نشد؛ محیط LaTeX باید آماده شود")
            version = subprocess.run([engine, "--version"], stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=15, check=False)
            report["engine_version"] = version.stdout.decode("utf-8", errors="replace").splitlines()[0]
            command = [engine, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                       "-file-line-error", "-output-directory=" + str(compiled.resolve()), "main.tex"]
            # MiKTeX must not open an installer prompt inside a noninteractive API call.
            if "miktex" in report["engine_version"].lower():
                command.insert(1, "--disable-installer")
            run(command, source)
            aux = compiled / "main.aux"
            if aux.is_file() and r"\bibdata{" in aux.read_text(encoding="utf-8", errors="replace"):
                bibtex = shutil.which("bibtex")
                if not bibtex:
                    raise ValueError("BibTeX برای مراجع این گزارش لازم است")
                # Resolve bibliography files relative to source without modifying global state.
                for path in source.rglob("*"):
                    if path.is_file() and path.suffix in {".bib", ".bst"}:
                        target = compiled / path.relative_to(source)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, target)
                run([bibtex, "main"], compiled)
                run(command, source)
            run(command, source)
            if re.search(r"Missing character:|There were undefined references|Citation .+ undefined", log[-1]):
                raise ValueError("نویسه یا ارجاع حل‌نشده در PDF؛ گزارش ابزار ساخت را بررسی کنید")
            pdf = compiled / "main.pdf"
            if not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF-"):
                raise ValueError("ابزار ساخت PDF معتبر تولید نکرد")
            report.update(status="built", pdf_sha256=_digest(pdf.read_bytes()), pdf_path=str(pdf.resolve()))
            return {"status": "built", "report": report,
                    "files": [{"role": "pdf", "path": str(pdf.resolve())},
                              {"role": "latex_source", "path": str(bundle.resolve())}]}
        except (OSError, ValueError, subprocess.TimeoutExpired, IndexError) as exc:
            message = str(exc)
            log_path.write_text("\n".join([*log, message]), encoding="utf-8")
            report["message"] = message
            return {"status": "needs_completion", "message": message, "report": report,
                    "files": [{"role": "latex_source", "path": str(bundle.resolve())}]}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return {"status": "needs_completion", "message": str(exc)}
