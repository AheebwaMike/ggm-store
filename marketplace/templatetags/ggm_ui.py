"""Small template helpers for the storefront UI."""
from django import template

register = template.Library()

# First match wins, so put the more specific keywords first.
# Edit freely: each entry is (keywords that may appear in the category name, emoji).
_EMOJI_RULES = (
    (('ice cream', 'frozen'), '🍦'),
    (('milk', 'dairy', 'yog', 'cheese', 'butter', 'ghee'), '🥛'),
    (('egg',), '🥚'),
    (('bread', 'bakery', 'bake', 'cake'), '🍞'),
    (('meat', 'chicken', 'beef', 'fish', 'poultry', 'sausage'), '🍗'),
    (('veg', 'tomato', 'onion', 'greens', 'produce'), '🥬'),
    (('fruit',), '🍎'),
    (('rice', 'flour', 'grain', 'maize', 'posho', 'cereal', 'oats'), '🌾'),
    (('pasta', 'noodle', 'spaghetti', 'macaroni'), '🍝'),
    (('bean', 'pea', 'lentil', 'nut', 'groundnut'), '🥜'),
    (('oil', 'cooking fat'), '🫒'),
    (('sugar', 'salt', 'spice', 'season', 'sauce', 'condiment'), '🧂'),
    (('can', 'tin', 'preserve', 'jam'), '🥫'),
    (('tea', 'coffee', 'cocoa'), '☕'),
    (('water', 'juice', 'soda', 'drink', 'beverage', 'soft'), '🥤'),
    (('beer', 'wine', 'spirit', 'liquor', 'alcohol'), '🍺'),
    (('biscuit', 'snack', 'sweet', 'candy', 'chocolate', 'crisps', 'chips'), '🍪'),
    (('baby', 'diaper', 'nappy', 'infant'), '🍼'),
    (('tooth', 'oral', 'dental'), '🪥'),
    (('soap', 'detergent', 'laundry', 'clean', 'bleach', 'wash'), '🧼'),
    (('toilet', 'tissue', 'paper', 'napkin', 'sanitary', 'pad'), '🧻'),
    (('cosmetic', 'beauty', 'lotion', 'hair', 'skin', 'body', 'personal', 'care'), '🧴'),
    (('medic', 'pharm', 'health', 'first aid'), '💊'),
    (('battery', 'bulb', 'electric', 'cable'), '🔋'),
    (('stationery', 'pen', 'book', 'school'), '✏️'),
    (('pet',), '🐾'),
    (('kitchen', 'utensil', 'plastic', 'household', 'home', 'cook'), '🍽️'),
)


@register.filter
def group_emoji(name):
    """Return an emoji for a product category name. Falls back to a shopping cart."""
    text = (name or '').lower()
    for keywords, emoji in _EMOJI_RULES:
        if any(keyword in text for keyword in keywords):
            return emoji
    return '🛒'


_ORDER_RANKS = {'new': 0, 'confirmed': 1, 'packed': 2, 'delivered': 3}


@register.filter
def order_rank(status):
    """Position of an order status in the tracking steps (0 = placed ... 3 = delivered)."""
    return _ORDER_RANKS.get(status, 0)