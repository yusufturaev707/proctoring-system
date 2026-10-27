"""
Oferta HTML'ini tozalash (`common.html_sanitizer`).

Matn panelda `dangerouslySetInnerHTML` bilan chiziladi — tozalashdan
o'tgan har narsa panelda ishlaydi. Shuning uchun testlar "nima QOLADI"
bilan birga "nima HECH QACHON o'tmaydi" ni ham tekshiradi.
"""

from django.test import SimpleTestCase

from apps.common.html_sanitizer import content_hash, html_text, sanitize_html


class SanitizeHtmlTests(SimpleTestCase):
    def test_editor_markup_is_kept(self):
        html = (
            "<h2>1. Umumiy qoidalar</h2><p><strong>Qalin</strong>, <em>kursiv</em>, "
            "<u>tagiga</u>, <s>ustiga</s></p><ul><li><p>band</p></li></ul>"
            "<ol><li>bir</li></ol><blockquote><p>iqtibos</p></blockquote><hr><p>a<br>b</p>"
        )
        self.assertEqual(sanitize_html(html), html)

    def test_script_and_style_removed_with_content(self):
        cleaned = sanitize_html("<p>ok</p><script>alert(1)</script><style>p{}</style>")
        self.assertEqual(cleaned, "<p>ok</p>")

    def test_event_handlers_and_unknown_attributes_dropped(self):
        cleaned = sanitize_html('<p onclick="x()" class="c" id="i">matn</p><img src=x onerror=alert(1)>')
        self.assertEqual(cleaned, "<p>matn</p>")

    def test_links_become_plain_text(self):
        cleaned = sanitize_html('<p><a href="javascript:alert(1)">bosing</a></p>')
        self.assertEqual(cleaned, "<p>bosing</p>")

    def test_unknown_tag_keeps_text(self):
        self.assertEqual(sanitize_html("<div><span>matn</span></div>"), "matn")

    def test_alignment_written_for_browser_and_qt(self):
        cleaned = sanitize_html('<p style="color: red; text-align: center">markaz</p>')
        self.assertEqual(cleaned, '<p style="text-align: center" align="center">markaz</p>')

    def test_left_alignment_is_default_and_omitted(self):
        self.assertEqual(sanitize_html('<p style="text-align: left">x</p>'), "<p>x</p>")

    def test_invalid_alignment_dropped(self):
        cleaned = sanitize_html('<p style="text-align: expression(alert(1))">x</p>')
        self.assertEqual(cleaned, "<p>x</p>")

    def test_text_is_escaped(self):
        self.assertEqual(sanitize_html("<p>&lt;script&gt; &amp; 5 &gt; 3</p>"),
                         "<p>&lt;script&gt; &amp; 5 &gt; 3</p>")

    def test_unclosed_tags_are_closed_and_stray_ends_ignored(self):
        self.assertEqual(sanitize_html("<p><strong>x</p></em>"), "<p><strong>x</strong></p>")

    def test_comments_removed(self):
        self.assertEqual(sanitize_html("<p>a<!-- <script> -->b</p>"), "<p>ab</p>")


class TextAndHashTests(SimpleTestCase):
    def test_html_text_strips_tags_and_collapses_space(self):
        self.assertEqual(html_text("<h1>Sarlavha</h1>\n<p>  bir   ikki </p>"), "Sarlavha bir ikki")

    def test_hash_is_stable_sha256(self):
        self.assertEqual(len(content_hash("<p>x</p>")), 64)
        self.assertEqual(content_hash("<p>x</p>"), content_hash("<p>x</p>"))
        self.assertNotEqual(content_hash("<p>x</p>"), content_hash("<p>y</p>"))
