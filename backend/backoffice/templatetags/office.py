from decimal import Decimal
from django import template
from django.utils.html import format_html
from django.utils.translation import get_language

register = template.Library()
TRANSLATIONS = {
    'Advertisements': 'რეკლამები', 'Cashier updates': 'სალაროს განახლებები',
    'Removal notice minutes': 'წაშლის შეტყობინების ხანგრძლივობა (წუთი)',
    'Overview': 'მიმოხილვა', 'Workspace': 'სამუშაო სივრცე', 'Management': 'მართვა', 'Settings': 'პარამეტრები',
    'Sales': 'გაყიდვები', 'Live checkouts': 'მიმდინარე კალათები', 'Products': 'პროდუქტები', 'Categories': 'კატეგორიები',
    'Branches': 'ფილიალები', 'Warehouses': 'საწყობები', 'Inventory': 'მარაგები', 'POS terminals': 'POS ტერმინალები',
    'Users': 'მომხმარებლები', 'Groups': 'ჯგუფები', 'Company settings': 'კომპანიის პარამეტრები', 'BackOffice': 'მართვის პანელი',
    'Sign out': 'გასვლა', 'Change password': 'პაროლის შეცვლა', 'Sign in': 'შესვლა', 'Welcome back': 'კეთილი იყოს თქვენი დაბრუნება',
    'Today’s sales': 'დღევანდელი გაყიდვები', 'Transactions': 'ტრანზაქციები', 'Average basket': 'საშუალო კალათა', 'Active branches': 'აქტიური ფილიალები',
    'Sales activity': 'გაყიდვების დინამიკა', 'Last 14 days': 'ბოლო 14 დღე', 'Recent sales': 'ბოლო გაყიდვები', 'View all': 'ყველას ნახვა',
    'Your branches': 'თქვენი ფილიალები', 'Your workspace, at a glance.': 'თქვენი სამუშაო სივრცის მიმოხილვა.',
    'Add product': 'პროდუქტის დამატება', 'Get your store ready': 'მოამზადეთ თქვენი მაღაზია', 'Create a branch': 'ფილიალის შექმნა',
    'Add your products': 'პროდუქტების დამატება', 'Connect a POS': 'POS-ის დაკავშირება', 'Ready': 'მზადაა', 'Next step': 'შემდეგი ნაბიჯი',
    'No sales yet': 'გაყიდვები ჯერ არ არის', 'Completed sales will appear here after a POS synchronizes.': 'დასრულებული გაყიდვები გამოჩნდება POS-ის სინქრონიზაციის შემდეგ.',
    'No branches yet': 'ფილიალები ჯერ არ არის', 'Search': 'ძებნა', 'Add': 'დამატება', 'Edit': 'შეცვლა', 'Save changes': 'ცვლილებების შენახვა',
    'Cancel': 'გაუქმება', 'Back': 'უკან', 'Active': 'აქტიური', 'Archived': 'არქივშია', 'Disabled': 'გამორთული', 'Actions': 'მოქმედებები',
    'No items yet': 'ჩანაწერები ჯერ არ არის', 'No matching items': 'ჩანაწერები ვერ მოიძებნა', 'Previous': 'წინა', 'Next': 'შემდეგი',
    'Branch': 'ფილიალი', 'Warehouse': 'საწყობი', 'Address': 'მისამართი', 'Code': 'კოდი', 'Status': 'სტატუსი', 'Product': 'პროდუქტი',
    'Barcode': 'შტრიხკოდი', 'Category': 'კატეგორია', 'Price': 'ფასი', 'Quantity': 'რაოდენობა', 'Location': 'მდებარეობა',
    'Group': 'ჯგუფი', 'Permissions': 'უფლებები', 'Georgian name': 'ქართული სახელი', 'POS terminal': 'POS ტერმინალი', 'Last seen': 'ბოლო კავშირი',
    'Pending POS requests': 'POS-ის დასადასტურებელი მოთხოვნები', 'Approve': 'დადასტურება', 'Reject': 'უარყოფა', 'Generate code': 'კოდის შექმნა',
    'Pair a POS': 'POS-ის დაკავშირება', 'Pairing code': 'დაკავშირების კოდი', 'Adjust stock': 'მარაგის კორექცია', 'Delete': 'წაშლა',
    'Create your workspace': 'შექმენით სამუშაო სივრცე', 'Create workspace': 'სივრცის შექმნა', 'Installation setup': 'ინსტალაციის გამართვა',
    'Unlock setup': 'გამართვის გახსნა', 'Installation setup key': 'ინსტალაციის გასაღები', 'Username': 'მომხმარებლის სახელი', 'Password': 'პაროლი',
    'Company name (ENG)': 'კომპანიის სახელი (ENG)', 'Company name (GEO)': 'კომპანიის სახელი (GEO)', 'Company address': 'კომპანიის მისამართი',
    'Company phone number': 'კომპანიის ტელეფონი', 'Admin first name': 'ადმინისტრატორის სახელი', 'Admin last name': 'ადმინისტრატორის გვარი',
    'Admin email': 'ადმინისტრატორის ელფოსტა', 'Admin username': 'ადმინისტრატორის მომხმარებლის სახელი', 'Admin password': 'ადმინისტრატორის პაროლი',
    'Confirm password': 'პაროლის გამეორება', 'First name': 'სახელი', 'Last name': 'გვარი', 'Email': 'ელფოსტა', 'Name': 'სახელი',
    'Initial branch or warehouse': 'საწყისი ფილიალი ან საწყობი', 'Selling price (GEL)': 'გასაყიდი ფასი (GEL)', 'Opening quantity': 'საწყისი რაოდენობა',
    'Product name (GEO)': 'პროდუქტის სახელი (GEO)', 'Allow all branches': 'ყველა ფილიალის დაშვება', 'Application': 'აპლიკაცია',
    'Add user': 'მომხმარებლის დამატება', 'Edit user': 'მომხმარებლის შეცვლა', 'Refresh': 'განახლება', 'Total': 'ჯამი', 'Cashier': 'მოლარე',
    'Time': 'დრო', 'Sale': 'გაყიდვა', 'Reason': 'მიზეზი', 'Request removal': 'წაშლის მოთხოვნა', 'Removal history': 'წაშლის ისტორია',
}

@register.filter
def tr(value):
    return TRANSLATIONS.get(str(value), value) if get_language().startswith('ka') else value

@register.filter
def money(value):
    return f'GEL {Decimal(value or 0) / 100:,.2f}'

@register.filter
def quantity(value):
    return f'{Decimal(value or 0) / 1000:g}'

PATHS = {
    'overview': 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    'sales': 'M4 19V9 M10 19V4 M16 19v-7 M22 19V2',
    'box': 'm3 7 9-5 9 5-9 5-9-5 M3 7v10l9 5 9-5V7 M12 12v10 M7 4.8l10 5.5',
    'store': 'M3 10V5h18v5 M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0 M5 13v8h14v-8 M9 21v-6h6v6',
    'users': 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.9 M16 3a4 4 0 0 1 0 8',
    'screen': 'M3 3h18v14H3z M8 21h8 M12 17v4',
    'tag': 'M3 3h8l10 10-8 8L3 11z M7 7h.01',
    'settings': 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
    'arrow': 'M5 12h14 M14 7l5 5-5 5', 'plus': 'M12 5v14 M5 12h14',
    'check': 'm5 12 4 4L19 6', 'clock': 'M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
    'menu': 'M3 6h18 M3 12h18 M3 18h18', 'search': 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    'wallet': 'M3 5h17v15H3z M3 5V3h14 M15 10h6v5h-6z',
}

@register.simple_tag
def icon(name):
    return format_html('<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{}"/></svg>', PATHS.get(name, PATHS['box']))
