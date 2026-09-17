from markdown_it import MarkdownIt
from markupsafe import Markup
import nh3

parser = MarkdownIt('commonmark', {'html': False, 'maxNesting': 20}).enable('table').disable('image')
TAGS = {'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote',
        'pre', 'code', 'strong', 'em', 's', 'ul', 'ol', 'li', 'a',
        'table', 'thead', 'tbody', 'tr', 'th', 'td'}


def render_markdown(value):
    return Markup(nh3.clean(parser.render(value), tags=TAGS,
        attributes={'a': {'href', 'title'}, 'ol': {'start'}},
        url_schemes={'http', 'https', 'mailto'}, link_rel='nofollow noopener noreferrer'))
