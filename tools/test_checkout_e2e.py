"""Real HTTP checkout test in an isolated temporary SQLite database; never uses a live DB."""
import os
import secrets
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main():
    with tempfile.TemporaryDirectory(prefix="simplepos-e2e-") as directory:
        os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", DB_ENGINE="sqlite", SIMPLEPOS_ALLOW_SQLITE="1",
            SIMPLEPOS_DATA_DIR=directory, SIMPLEPOS_DEBUG="1", SIMPLEPOS_HTTPS="0",
            SIMPLEPOS_ALLOWED_HOSTS="127.0.0.1,localhost", SIMPLEPOS_SECRET_KEY="e2e-only-not-a-real-secret-with-more-than-fifty-characters")
        sys.path.insert(0, str(BACKEND))
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connection
        from django.contrib.auth import get_user_model
        from commerce.models import EmployeeAccess, AccessPermission, LiveBasket, BasketCommand
        from commerce.supervision import request_removal
        from commerce.models import Company, Location, Product, Register, StockItem, StockAdjustment, Sale, StockMovement
        call_command("migrate", verbosity=0, interactive=False)
        company = Company.objects.create(code="e2e", name="Test market")
        branch = Location.objects.create(company=company, code="store", kind="branch", name="Store")
        product = Product.objects.create(company=company, home_location=branch, barcode="001", name="Milk", price_minor=450)
        stock = StockItem.objects.get(product=product, location=branch)
        StockAdjustment.objects.create(stock_item=stock, quantity_milli=10000, reason="Opening")
        register = Register.objects.create(location=branch, code="pos", name="POS")
        token = register.issue_token()
        password = secrets.token_urlsafe(24)
        user = get_user_model().objects.create_user(username="cashier", password=password)
        EmployeeAccess.objects.create(user=user, company=company, application="cashier", all_branches=True)
        manager = get_user_model().objects.create_user(username="manager")
        access = EmployeeAccess.objects.create(user=manager, company=company, application="backend", all_branches=True)
        access.permissions.add(AccessPermission.objects.get(pk="supervise_basket"))
        connection.close()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        with open(Path(directory) / "server.log", "w+") as log:
            server = subprocess.Popen([sys.executable, "-m", "gunicorn", "config.wsgi:application", "--bind", f"127.0.0.1:{port}", "--workers", "1"], cwd=BACKEND, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        log.seek(0)
                        raise RuntimeError("Test server failed: " + log.read())
                    try:
                        with urlopen(origin + "/healthz/", timeout=1) as response:
                            if response.status == 200: break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Test server did not become ready")
                client = subprocess.Popen(["node", str(Path(os.environ.get("CASHIER_SOURCE_DIR", ROOT.parent / "pos-cashier")) / "tools/checkout_e2e.cjs")], text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    env={**os.environ, "TEST_ORIGIN": origin, "TEST_TOKEN": token, "TEST_PASSWORD": password, "TEST_LOCAL_DB": str(Path(directory) / "cashier.sqlite")})
                try:
                    for line in client.stdout:
                        if line.strip() == "REQUEST_REMOVAL":
                            snapshot = LiveBasket.objects.get(register=register)
                            import json
                            request_removal(manager, register.pk, snapshot.basket_id, snapshot.revision, json.loads(snapshot.lines_json)[0]["key"], "E2E supervisor removal")
                            client.stdin.write("continue\n")
                            client.stdin.flush()
                    if client.wait(timeout=30) != 0: raise RuntimeError("Cashier HTTP test failed")
                finally:
                    if client.poll() is None: client.kill(); client.wait()
                    client.stdin.close(); client.stdout.close()
                assert BasketCommand.objects.get().status == "applied", "Remote removal was not acknowledged"
                assert Sale.objects.count() == 1, "Retries duplicated the sale"
                assert StockMovement.objects.filter(reason="cash_sale").count() == 1, "Retries duplicated stock movement"
                stock.refresh_from_db()
                assert stock.quantity_milli == 8000, stock.quantity_milli
                print("HTTP integration passed: enrollment + offline login + manager removal + offline restart + lost acknowledgement -> one sale and one stock deduction.")
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                connection.close()


if __name__ == "__main__":
    main()
