"""Create a readable local PDF snapshot from an allow-listed policy page."""
import argparse
import asyncio
import html
import os
import re
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .scraper import DEFAULT_POLICY_URL, fetch_article_document


def _register_fonts():
    candidates = [
        (os.getenv("POLICY_PDF_FONT"), os.getenv("POLICY_PDF_BOLD_FONT")),
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if regular and bold and Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("PolicySans", regular))
            pdfmetrics.registerFont(TTFont("PolicySans-Bold", bold))
            return
    raise RuntimeError("A Unicode TrueType font is required to create the policy PDF")


def build_policy_pdf(article, output_path):
    _register_fonts()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=article["title"], author="Ecommerce Customer Service RAG",
        subject=f"Local snapshot of {article['sourceUrl']}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PolicyTitle", parent=styles["Title"], fontName="PolicySans-Bold",
        fontSize=20, leading=25, textColor=HexColor("#EE4D2D"), alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )
    metadata_style = ParagraphStyle(
        "PolicyMetadata", parent=styles["Normal"], fontName="PolicySans",
        fontSize=8.5, leading=12, textColor=HexColor("#555555"), spaceAfter=2 * mm,
    )
    heading_style = ParagraphStyle(
        "PolicyHeading", parent=styles["Heading2"], fontName="PolicySans-Bold",
        fontSize=12, leading=16, textColor=HexColor("#222222"),
        spaceBefore=5 * mm, spaceAfter=2 * mm, keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "PolicyBody", parent=styles["BodyText"], fontName="PolicySans",
        fontSize=9.5, leading=14, textColor=HexColor("#222222"),
        spaceAfter=2.5 * mm, splitLongWords=True,
    )
    story = [
        Paragraph(html.escape(article["title"]), title_style),
        Paragraph("Bản lưu cục bộ phục vụ Customer Service RAG", metadata_style),
        Paragraph(
            f'Nguồn chính thức: <link href="{html.escape(article["sourceUrl"])}" color="#1A73E8">'
            f'{html.escape(article["sourceUrl"])}</link>', metadata_style,
        ),
        Paragraph(f'Thời điểm thu thập (UTC): {html.escape(article["crawledAt"])}', metadata_style),
        Paragraph(f'SHA-256 nội dung: {article["hash"]}', metadata_style),
    ]
    if article.get("category"):
        story.append(Paragraph(f'Nhóm: {html.escape(article["category"])}', metadata_style))
    if article.get("subcategory"):
        story.append(Paragraph(f'Danh mục: {html.escape(article["subcategory"])}', metadata_style))
    story.append(Spacer(1, 4 * mm))
    for paragraph in article["paragraphs"]:
        escaped = html.escape(paragraph)
        is_heading = len(paragraph) < 180 and (
            paragraph == paragraph.upper() or re.fullmatch(r"\d+\.\s+.+", paragraph)
        )
        story.append(Paragraph(escaped, heading_style if is_heading else body_style))

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setTitle(article["title"])
        canvas.setAuthor("Ecommerce Customer Service RAG")
        canvas.setFont("PolicySans", 7.5)
        canvas.setFillColor(HexColor("#777777"))
        canvas.drawString(20 * mm, 10 * mm, "Nguồn: help.shopee.vn - bản snapshot local")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Trang {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output


async def create_pdf(source_url, output_path):
    article = await fetch_article_document(source_url)
    article.pop("html", None)
    return build_policy_pdf(article, output_path)


def main():
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=DEFAULT_POLICY_URL)
    parser.add_argument("--output", default=str(repository / "output" / "pdf" / "shopee-privacy-policy.pdf"))
    args = parser.parse_args()
    print(asyncio.run(create_pdf(args.source, args.output)))


if __name__ == "__main__":
    main()
