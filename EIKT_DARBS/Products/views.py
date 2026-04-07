from django.shortcuts import render
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from .models import Product
from django.db import connection
import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt


def normalize_text(text):
    """Strip accents, punctuation, spaces and lowercase. Used for search matching."""
    if text is None:
        return ""
    s = str(text)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'\s+', ' ', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9]+', ' ', s)
    return re.sub(r' +', ' ', s).strip().replace(' ', '').lower()


def parse_decimal(value, default=None):
    """Parse a price string into Decimal, handling European formats and currency symbols."""
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    s = s.replace('\u00A0', '')
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    s = re.sub(r'[^0-9\.\-Ee+]', '', s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return default


def quick_sort(arr, key=lambda x: x, reverse=False):
    """Quicksort using middle element as pivot to avoid worst case on sorted data."""
    if len(arr) <= 1:
        return list(arr)
    pivot_key = key(arr[len(arr) // 2])
    left  = [x for x in arr if key(x) <  pivot_key]
    mid   = [x for x in arr if key(x) == pivot_key]
    right = [x for x in arr if key(x) >  pivot_key]
    if reverse:
        return quick_sort(right, key, reverse) + mid + quick_sort(left, key, reverse)
    return quick_sort(left, key, reverse) + mid + quick_sort(right, key, reverse)


def binary_search_left(arr, keyfunc, target):
    """First index where keyfunc(item) >= target. Used for price range lower bound."""
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if keyfunc(arr[mid]) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def binary_search_right(arr, keyfunc, target):
    """One past last index where keyfunc(item) <= target. Used for price range upper bound."""
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if keyfunc(arr[mid]) <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def compute_relevance(prod, tokens):
    """Score how well a product matches search tokens. Name matches worth 5x more than description."""
    if not tokens:
        return 0
    name_norm = prod.get('name_normalized') or ''
    desc_norm = prod.get('description_normalized') or ''
    score = 0
    for t in tokens:
        score += 10 * name_norm.count(t)
        score += 2  * desc_norm.count(t)
    return score


def page_window(page, total_pages, wing=2):
    """Build pagination bar numbers. Returns None as placeholder for '...' gaps."""
    if total_pages <= 1:
        return []
    pages = [1]
    left  = max(2, page - wing)
    right = min(total_pages - 1, page + wing)
    if left > 2:
        pages.append(None)
    pages.extend(range(left, right + 1))
    if right < total_pages - 1:
        pages.append(None)
    pages.append(total_pages)
    return pages


def products_search(request):
    params    = request.GET
    q         = params.get('q', '').strip()
    tokens    = [normalize_text(part) for part in q.split() if normalize_text(part)]
    category  = params.get('category', '').strip()
    brand     = params.get('brand', '').strip()
    available = params.get('available', '').strip()
    min_price = params.get('min_price', '').strip()
    max_price = params.get('max_price', '').strip()
    sort      = params.get('sort', 'relevance' if q else 'date_desc')
    PAGE_SIZE = 50

    try:
        page = int(params.get('page', '1') or 1)
    except (TypeError, ValueError):
        page = 1

    # Load products from DB
    try:
        products = list(Product.objects.all().values(
            'id', 'company', 'category', 'name', 'name_normalized',
            'description', 'description_normalized', 'price', 'available', 'rating', 'created_at'
        ))
    except InvalidOperation:
        # Fallback to raw SQL if ORM trips over a malformed Decimal
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, company, category, name, name_normalized, description, description_normalized, price, available, rating, created_at FROM Products_product"
            )
            cols = [c[0] for c in cursor.description]
            products = []
            for row in cursor.fetchall():
                d = dict(zip(cols, row))
                d['price']  = parse_decimal(d.get('price'),  Decimal('0.00')) or Decimal('0.00')
                d['rating'] = parse_decimal(d.get('rating'), Decimal('0.00')) or Decimal('0.00')
                products.append(d)

    # Collect unique categories and brands for filter dropdowns
    categories = sorted({p.get('category') or '' for p in products} - {''})
    brands     = sorted({p.get('company')  or '' for p in products} - {''})

    # Price range filter using binary search on a sorted list
    available_bool = available.lower() in ('1', 'true', 'yes', 'y', 'on') if available else None
    min_p = parse_decimal(min_price, None)
    max_p = parse_decimal(max_price, None)

    if min_p is not None or max_p is not None:
        price_sorted = quick_sort(products, key=lambda p: p['price'])
        low  = binary_search_left( price_sorted, lambda p: p['price'], min_p) if min_p is not None else 0
        high = binary_search_right(price_sorted, lambda p: p['price'], max_p) if max_p is not None else len(price_sorted)
        products = price_sorted[low:high]

    # Remaining filters - text search is a linear search through all products
    def matches(prod):
        if category and (prod.get('category') or '').strip().lower() != category.lower():
            return False
        if brand and (prod.get('company') or '').strip().lower() != brand.lower():
            return False
        if available_bool is not None and prod.get('available') != available_bool:
            return False
        if tokens:
            name_norm = prod.get('name_normalized') or ''
            desc_norm = prod.get('description_normalized') or ''
            if not any(t in name_norm or t in desc_norm for t in tokens):
                return False
        return True

    filtered = [p for p in products if matches(p)]

    # Score and sort
    if tokens:
        for p in filtered:
            p['_relevance'] = compute_relevance(p, tokens)

    sort_map = {
        'relevance':  (lambda p: p.get('_relevance', 0), True),
        'price_asc':  (lambda p: p['price'], False),
        'price_desc': (lambda p: p['price'], True),
        'rating':     (lambda p: p.get('rating', 0), True),
        'date_asc':   (lambda p: p.get('created_at'), False),
        'date_desc':  (lambda p: p.get('created_at'), True),
    }
    sort_key, sort_reverse = sort_map.get(sort, sort_map['date_desc'])
    filtered = quick_sort(filtered, key=sort_key, reverse=sort_reverse)

    # Paginate
    total       = len(filtered)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 0
    page        = max(1, min(page, total_pages)) if total_pages else 1
    page_items  = filtered[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    return render(request, 'products/list.html', {
        'products':    page_items,
        'q':           q,
        'category':    category,
        'brand':       brand,
        'min_price':   min_price,
        'max_price':   max_price,
        'available':   available,
        'sort':        sort,
        'page':        page,
        'total_pages': total_pages,
        'total':       total,
        'categories':  categories,
        'brands':      brands,
        'pages':       page_window(page, total_pages),
    })


@csrf_exempt
def api_add_product(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body.decode('utf-8') if request.body else '{}')
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    
        description = item.get('description', '')
        return Product(
            company                = item.get('company', ''),
            category               = item.get('category', ''),
            name                   = name,
            name_normalized        = normalize_text(item.get('name_normalized') or name),
            description            = description,
            description_normalized = normalize_text(item.get('description_normalized') or description),
            price                  = parse_decimal(item.get('price', '0'), Decimal('0.00')),
            available              = bool(item.get('available', True)),
            rating                 = parse_decimal(item.get('rating', 0), Decimal('0.00')),
        )

    if isinstance(data, list):
        Product.objects.bulk_create([build_product(item) for item in data])
        return JsonResponse({'created': len(data)}, status=201)

    if isinstance(data, dict):
        price_dec = parse_decimal(data.get('price', '0'), None)
        if price_dec is None:
            return HttpResponseBadRequest('Invalid price')
        prod = build_product(data)
        prod.price = price_dec
        prod.save()
        return JsonResponse({'id': prod.id, 'name': prod.name}, status=201)

    return HttpResponseBadRequest('JSON must be object or list')