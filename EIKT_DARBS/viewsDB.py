from django.shortcuts import render
from django.db import connection
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal, InvalidOperation
import re, unicodedata, json


def normalize_text(text):
    if text is None: return ""
    s = unicodedata.normalize('NFKD', str(text))
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9]+', '', s)
    return s.lower()


def parse_decimal(value, default=None):
    if value is None: return default
    s = str(value).strip().replace('\u00A0', '')
    if ',' in s and '.' in s:  s = s.replace(',', '')
    elif ',' in s:              s = s.replace(',', '.')
    s = re.sub(r'[^0-9.\-Ee+]', '', s)
    try:    return Decimal(s)
    except InvalidOperation: return default


def page_window(page, total_pages, wing=2):
    if total_pages <= 1: return []
    pages = [1]
    left  = max(2, page - wing)
    right = min(total_pages - 1, page + wing)
    if left  > 2:             pages.append(None)
    pages.extend(range(left, right + 1))
    if right < total_pages-1: pages.append(None)
    if total_pages > 1:       pages.append(total_pages)
    return pages


PAGE_SIZE = 50

SORT_MAP = {
    'price_asc':  'price ASC',
    'price_desc': 'price DESC',
    'rating':     'rating DESC',
    'date_asc':   'created_at ASC',
    'date_desc':  'created_at DESC',
}


def products_search(request):
    p             = request.GET
    q             = p.get('q', '').strip()
    token         = normalize_text(q) if q else None
    category      = p.get('category', '').strip()
    brand         = p.get('brand', '').strip()
    available_raw = p.get('available', '').strip()
    min_price     = parse_decimal(p.get('min_price', ''), None)
    max_price     = parse_decimal(p.get('max_price', ''), None)
    sort          = p.get('sort', 'relevance' if q else 'date_desc')
    try:    page = max(1, int(p.get('page', 1) or 1))
    except: page = 1

    available_bool = (
        available_raw.lower() in ('1', 'true', 'yes', 'y', 'on')
        if available_raw else None
    )

    # build WHERE
    wheres, args = [], []

    if token:
        wheres.append("(name_normalized LIKE %s OR description_normalized LIKE %s)")
        like = f'%{token}%'
        args += [like, like]

    if category:
        wheres.append("LOWER(category) = LOWER(%s)")
        args.append(category)

    if brand:
        wheres.append("LOWER(company) = LOWER(%s)")
        args.append(brand)

    if available_bool is not None:
        wheres.append("available = %s")
        args.append(available_bool)

    if min_price is not None:
        wheres.append("price >= %s")
        args.append(min_price)

    if max_price is not None:
        wheres.append("price <= %s")
        args.append(max_price)

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    # relevance column
    if token:
        relevance_col  = "CASE WHEN name_normalized LIKE %s THEN 2 WHEN description_normalized LIKE %s THEN 1 ELSE 0 END AS _relevance"
        relevance_args = [f'%{token}%', f'%{token}%']
    else:
        relevance_col  = "0 AS _relevance"
        relevance_args = []

    # ORDER BY
    if sort == 'relevance' and token:
        order_sql = "ORDER BY _relevance DESC, created_at DESC"
    else:
        order_sql = f"ORDER BY {SORT_MAP.get(sort, 'created_at DESC')}"

    # count (no data fetched)
    with connection.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM products_product {where_sql}", args)
        total = cur.fetchone()[0]

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 0
    page        = max(1, min(page, total_pages)) if total_pages else 1
    offset      = (page - 1) * PAGE_SIZE

    # data page
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT id, company, category, name, description,
                   price, available, rating, created_at,
                   {relevance_col}
            FROM   products_product
            {where_sql}
            {order_sql}
            LIMIT %s OFFSET %s
        """, relevance_args + args + [PAGE_SIZE, offset])
        cols     = [c[0] for c in cur.description]
        products = [dict(zip(cols, row)) for row in cur.fetchall()]

    # facets
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT category FROM products_product WHERE category != '' ORDER BY category")
        categories = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT company FROM products_product WHERE company != '' ORDER BY company")
        brands = [r[0] for r in cur.fetchall()]

    context = dict(
        products=products, q=q, category=category, brand=brand,
        min_price=p.get('min_price', ''), max_price=p.get('max_price', ''),
        available=available_raw, sort=sort, page=page,
        total_pages=total_pages, total=total,
        categories=categories, brands=brands,
        pages=page_window(page, total_pages),
    )
    return render(request, 'products/list.html', context)


@csrf_exempt
def api_add_product(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = request.body.decode('utf-8') if request.body else ''
        data = json.loads(body) if body else {}
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')

    def row(item):
        name = item.get('name', '')
        desc = item.get('description', '')
        return (
            item.get('company', ''),
            item.get('category', ''),
            name,
            normalize_text(item.get('name_normalized') or name),
            desc,
            normalize_text(item.get('description_normalized') or desc),
            parse_decimal(item.get('price', '0'), Decimal('0.00')),
            bool(item.get('available', True)),
            parse_decimal(item.get('rating', 0), Decimal('0.00')),
        )

    INSERT = """
        INSERT INTO products_product
            (company, category, name, name_normalized,
             description, description_normalized, price, available, rating)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    if isinstance(data, list):
        rows = [row(i) for i in data]
        with connection.cursor() as cur:
            cur.executemany(INSERT, rows)
        return JsonResponse({'created': len(rows)}, status=201)

    if isinstance(data, dict):
        price_dec = parse_decimal(data.get('price', '0'), None)
        if price_dec is None:
            return HttpResponseBadRequest('Invalid price')
        with connection.cursor() as cur:
            cur.execute(INSERT + " RETURNING id", row(data))
            new_id = cur.fetchone()[0]
        return JsonResponse({'id': new_id, 'name': data.get('name')}, status=201)

    return HttpResponseBadRequest('JSON must be object or list')