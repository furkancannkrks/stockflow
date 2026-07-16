import os
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.inventory.models import Inventory, StockMovement
from apps.orders.models import Order, OrderItem
from apps.products.models import Product, Warehouse
from apps.users.models import User


WAREHOUSE_DEFINITIONS = (
    ("MAIN", "Main Warehouse", "100 Operations Avenue"),
    ("EAST", "East Warehouse", "25 East Logistics Road"),
    ("WEST", "West Warehouse", "80 West Distribution Street"),
)

PRODUCT_DEFINITIONS = (
    ("MECH-KB-001", "Mechanical Keyboard", "Peripherals", "89.90", 5),
    ("USBC-HUB-001", "USB-C Hub", "Accessories", "49.50", 5),
    ("WIRELESS-MOUSE-001", "Wireless Mouse", "Peripherals", "34.90", 4),
    ("MONITOR-27-001", "27-inch Monitor", "Displays", "279.00", 3),
    ("LAPTOP-STAND-001", "Laptop Stand", "Accessories", "42.00", 4),
    ("HEADPHONES-NC-001", "Noise-Cancelling Headphones", "Audio", "159.00", 3),
    ("WEBCAM-HD-001", "HD Webcam", "Peripherals", "65.00", 4),
    ("DESK-LAMP-001", "LED Desk Lamp", "Office", "38.50", 5),
    ("EXT-SSD-1TB-001", "External SSD 1TB", "Storage", "119.00", 3),
    ("USBC-CABLE-001", "USB-C Cable", "Cables", "14.90", 8),
    ("HDMI-CABLE-001", "HDMI Cable", "Cables", "16.50", 8),
    ("ETH-ADAPTER-001", "Ethernet Adapter", "Networking", "29.90", 5),
    ("POWER-BANK-001", "Portable Charger", "Power", "54.00", 4),
    ("BT-SPEAKER-001", "Bluetooth Speaker", "Audio", "72.00", 4),
    ("ERG-CHAIR-001", "Ergonomic Chair", "Furniture", "349.00", 2),
    ("STAND-DESK-001", "Standing Desk", "Furniture", "599.00", 2),
    ("NOTEBOOK-PACK-001", "Notebook Pack", "Office", "18.00", 10),
    ("GEL-PEN-SET-001", "Gel Pen Set", "Office", "12.50", 10),
    ("LABEL-PRINTER-001", "Label Printer", "Warehouse", "139.00", 3),
    ("BARCODE-SCANNER-001", "Barcode Scanner", "Warehouse", "95.00", 3),
    ("THERMAL-ROLL-001", "Thermal Paper Roll", "Warehouse", "8.50", 12),
    ("PACKING-TAPE-001", "Packing Tape", "Shipping", "6.90", 15),
    ("BOX-SMALL-001", "Shipping Box Small", "Shipping", "2.20", 20),
    ("BOX-MEDIUM-001", "Shipping Box Medium", "Shipping", "3.40", 20),
    ("BOX-LARGE-001", "Shipping Box Large", "Shipping", "5.60", 15),
    ("SAFETY-GLOVES-001", "Safety Gloves", "Safety", "11.00", 8),
    ("CABLE-ORG-001", "Cable Organizer", "Accessories", "9.90", 8),
    ("SURGE-PROTECT-001", "Surge Protector", "Power", "31.00", 5),
    ("DISPLAYPORT-001", "DisplayPort Cable", "Cables", "19.50", 8),
    ("CLEANING-KIT-001", "Electronics Cleaning Kit", "Maintenance", "17.90", 6),
)

ORDER_DEFINITIONS = (
    {
        "number": "SEED-ORD-DRAFT",
        "customer_name": "Draft Customer",
        "customer_email": "draft.customer@example.com",
        "status": Order.Status.DRAFT,
        "reserved_minutes_ago": None,
        "items": (("LAPTOP-STAND-001", "MAIN", 2),),
    },
    {
        "number": "SEED-ORD-INSUFFICIENT",
        "customer_name": "Insufficient Stock Customer",
        "customer_email": "insufficient.customer@example.com",
        "status": Order.Status.DRAFT,
        "reserved_minutes_ago": None,
        "items": (
            ("MECH-KB-001", "MAIN", 3),
            ("USBC-HUB-001", "MAIN", 2),
        ),
    },
    {
        "number": "SEED-ORD-CANCEL",
        "customer_name": "Cancellation Test Customer",
        "customer_email": "cancel.customer@example.com",
        "status": Order.Status.RESERVED,
        "reserved_minutes_ago": 10,
        "items": (("MECH-KB-001", "MAIN", 3),),
    },
    {
        "number": "SEED-ORD-EXPIRED",
        "customer_name": "Expiration Test Customer",
        "customer_email": "expiration.customer@example.com",
        "status": Order.Status.RESERVED,
        "reserved_minutes_ago": 45,
        "items": (("MECH-KB-001", "MAIN", 5),),
    },
    {
        "number": "SEED-ORD-RESERVED",
        "customer_name": "Reserved Customer",
        "customer_email": "reserved.customer@example.com",
        "status": Order.Status.RESERVED,
        "reserved_minutes_ago": 5,
        "items": (("USBC-HUB-001", "MAIN", 5),),
    },
    {
        "number": "SEED-ORD-CONFIRMED",
        "customer_name": "Confirmed Customer",
        "customer_email": "confirmed.customer@example.com",
        "status": Order.Status.CONFIRMED,
        "reserved_minutes_ago": 90,
        "items": (("WIRELESS-MOUSE-001", "EAST", 2),),
    },
    {
        "number": "SEED-ORD-CANCELLED",
        "customer_name": "Cancelled Customer",
        "customer_email": "cancelled.customer@example.com",
        "status": Order.Status.CANCELLED,
        "reserved_minutes_ago": 75,
        "items": (("WEBCAM-HD-001", "EAST", 1),),
    },
    {
        "number": "SEED-ORD-SHIPPED",
        "customer_name": "Shipped Customer",
        "customer_email": "shipped.customer@example.com",
        "status": Order.Status.SHIPPED,
        "reserved_minutes_ago": 180,
        "items": (("EXT-SSD-1TB-001", "MAIN", 1),),
    },
)

DEMO_USERS = (
    (
        "demo_manager",
        User.Role.MANAGER,
        "demo.manager@example.com",
        "STOCKFLOW_DEMO_MANAGER_PASSWORD",
    ),
    (
        "demo_warehouse_staff",
        User.Role.WAREHOUSE_STAFF,
        "demo.warehouse@example.com",
        "STOCKFLOW_DEMO_STAFF_PASSWORD",
    ),
)


class Command(BaseCommand):
    help = "Create or reconcile deterministic StockFlow demonstration data."

    def handle(self, *args, **options):
        created_counts = Counter()

        with transaction.atomic():
            users, password_states = self._seed_users(created_counts)
            warehouses = self._seed_warehouses(created_counts)
            products = self._seed_products(created_counts)
            inventories = self._seed_inventories(
                products,
                warehouses,
                created_counts,
            )
            orders = self._seed_orders(
                products,
                warehouses,
                created_counts,
            )
            movement_ids = self._seed_movements(
                inventories,
                orders,
                users["demo_manager"],
                created_counts,
            )
            audit_ids = self._seed_audit_logs(
                inventories,
                orders,
                users["demo_manager"],
                created_counts,
            )

        self._write_summary(
            inventories=inventories,
            orders=orders,
            movement_count=len(movement_ids),
            audit_count=len(audit_ids),
            created_counts=created_counts,
            password_states=password_states,
        )

    def _seed_users(self, created_counts):
        users = {}
        password_states = {}

        for username, role, email, password_env in DEMO_USERS:
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "email": email,
                    "role": role,
                    "is_active": True,
                },
            )
            created_counts["users"] += int(created)
            password = os.getenv(password_env, "")

            if password:
                if not user.check_password(password):
                    user.set_password(password)
                    user.save(update_fields=["password"])
                password_states[username] = f"configured from {password_env}"
            elif created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
                password_states[username] = f"unusable; set {password_env}"
            elif user.has_usable_password():
                password_states[username] = "existing password preserved"
            else:
                password_states[username] = f"unusable; set {password_env}"

            users[username] = user

        return users, password_states

    def _seed_warehouses(self, created_counts):
        warehouses = {}
        for code, name, address in WAREHOUSE_DEFINITIONS:
            warehouse, created = Warehouse.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "address": address,
                    "is_active": True,
                },
            )
            created_counts["warehouses"] += int(created)
            warehouses[code] = warehouse
        return warehouses

    def _seed_products(self, created_counts):
        products = {}
        for sku, name, category, price, threshold in PRODUCT_DEFINITIONS:
            product, created = Product.objects.update_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": category,
                    "unit_price": Decimal(price),
                    "low_stock_threshold": threshold,
                    "is_active": True,
                },
            )
            created_counts["products"] += int(created)
            products[sku] = product
        return products

    def _seed_inventories(self, products, warehouses, created_counts):
        inventories = {}
        warehouse_offsets = {"MAIN": 0, "EAST": 1, "WEST": 2}

        for index, (sku, *_product_data) in enumerate(PRODUCT_DEFINITIONS):
            warehouse_codes = ("MAIN", "EAST") if index < 15 else ("MAIN", "WEST")
            for warehouse_code in warehouse_codes:
                quantity = 18 + (
                    (index * 7 + warehouse_offsets[warehouse_code] * 5) % 33
                )
                reserved_quantity = 0
                if sku == "MECH-KB-001" and warehouse_code == "MAIN":
                    quantity = 10
                    reserved_quantity = 8
                elif sku == "USBC-HUB-001" and warehouse_code == "MAIN":
                    quantity = 20
                    reserved_quantity = 5

                inventory, created = Inventory.objects.update_or_create(
                    product=products[sku],
                    warehouse=warehouses[warehouse_code],
                    defaults={
                        "quantity": quantity,
                        "reserved_quantity": reserved_quantity,
                    },
                )
                created_counts["inventories"] += int(created)
                inventories[(sku, warehouse_code)] = inventory

        return inventories

    def _seed_orders(self, products, warehouses, created_counts):
        orders = {}
        now = timezone.now()

        for definition in ORDER_DEFINITIONS:
            reserved_minutes_ago = definition["reserved_minutes_ago"]
            reserved_at = (
                now - timedelta(minutes=reserved_minutes_ago)
                if reserved_minutes_ago is not None
                else None
            )
            order, created = Order.objects.update_or_create(
                order_number=definition["number"],
                defaults={
                    "customer_name": definition["customer_name"],
                    "customer_email": definition["customer_email"],
                    "status": definition["status"],
                    "total_amount": Decimal("0.00"),
                    "reserved_at": reserved_at,
                },
            )
            created_counts["orders"] += int(created)

            total_amount = Decimal("0.00")
            item_ids = []
            for sku, warehouse_code, quantity in definition["items"]:
                product = products[sku]
                subtotal = Decimal(quantity) * product.unit_price
                item, item_created = OrderItem.objects.update_or_create(
                    order=order,
                    product=product,
                    warehouse=warehouses[warehouse_code],
                    defaults={
                        "quantity": quantity,
                        "unit_price": product.unit_price,
                        "subtotal": subtotal,
                    },
                )
                created_counts["order_items"] += int(item_created)
                item_ids.append(item.id)
                total_amount += subtotal

            order.items.exclude(id__in=item_ids).delete()
            order.total_amount = total_amount
            order.status = definition["status"]
            order.reserved_at = reserved_at
            order.save(
                update_fields=[
                    "total_amount",
                    "status",
                    "reserved_at",
                    "updated_at",
                ]
            )
            orders[definition["number"]] = order

        return orders

    def _seed_movements(self, inventories, orders, actor, created_counts):
        movement_ids = set()
        stock_out_totals = Counter()

        for definition in ORDER_DEFINITIONS:
            if definition["status"] in {Order.Status.CONFIRMED, Order.Status.SHIPPED}:
                for sku, warehouse_code, quantity in definition["items"]:
                    stock_out_totals[(sku, warehouse_code)] += quantity

        for (sku, warehouse_code), inventory in inventories.items():
            movement, created = self._upsert_movement(
                inventory=inventory,
                movement_type=StockMovement.MovementType.STOCK_IN,
                quantity=inventory.quantity + stock_out_totals[(sku, warehouse_code)],
                reference_type="seed_data",
                reference_id=f"initial:{sku}:{warehouse_code}",
                description="Initial stock for the deterministic seed dataset.",
                actor=actor,
            )
            created_counts["stock_movements"] += int(created)
            movement_ids.add(movement.id)

        for definition in ORDER_DEFINITIONS:
            order = orders[definition["number"]]
            movement_types = self._movement_types_for_status(definition["status"])
            for sku, warehouse_code, quantity in definition["items"]:
                inventory = inventories[(sku, warehouse_code)]
                for movement_type in movement_types:
                    movement, created = self._upsert_movement(
                        inventory=inventory,
                        movement_type=movement_type,
                        quantity=quantity,
                        reference_type="order",
                        reference_id=str(order.id),
                        description=self._movement_description(
                            order,
                            movement_type,
                        ),
                        actor=actor,
                    )
                    created_counts["stock_movements"] += int(created)
                    movement_ids.add(movement.id)

        return movement_ids

    def _upsert_movement(
        self,
        *,
        inventory,
        movement_type,
        quantity,
        reference_type,
        reference_id,
        description,
        actor,
    ):
        movement = (
            StockMovement.objects.filter(
                inventory=inventory,
                movement_type=movement_type,
                reference_type=reference_type,
                reference_id=reference_id,
            )
            .order_by("id")
            .first()
        )
        created = movement is None
        if created:
            movement = StockMovement.objects.create(
                inventory=inventory,
                movement_type=movement_type,
                quantity=quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                description=description,
                created_by=actor,
            )
        else:
            movement.quantity = quantity
            movement.description = description
            movement.created_by = actor
            movement.save(update_fields=["quantity", "description", "created_by"])
        return movement, created

    def _seed_audit_logs(self, inventories, orders, actor, created_counts):
        audit_ids = set()

        for (sku, warehouse_code), inventory in list(inventories.items())[:5]:
            audit, created = self._upsert_audit(
                correlation_id=f"seed:inventory:{sku}:{warehouse_code}",
                actor=actor,
                action=AuditLog.Action.INVENTORY_ADJUSTED,
                target=inventory,
                metadata={
                    "source": "seed_data",
                    "adjustment_type": "stock_in",
                    "quantity": {"before": 0, "after": inventory.quantity},
                    "reserved_quantity": {
                        "before": 0,
                        "after": inventory.reserved_quantity,
                    },
                    "product": {"id": inventory.product_id, "sku": sku},
                    "warehouse": {
                        "id": inventory.warehouse_id,
                        "code": warehouse_code,
                    },
                },
            )
            created_counts["audit_logs"] += int(created)
            audit_ids.add(audit.id)

        for definition in ORDER_DEFINITIONS:
            if definition["status"] == Order.Status.DRAFT:
                continue

            order = orders[definition["number"]]
            reserved_audit, created = self._upsert_audit(
                correlation_id=f"seed:order:{order.order_number}:reserved",
                actor=actor,
                action=AuditLog.Action.ORDER_RESERVED,
                target=order,
                metadata=self._order_audit_metadata(
                    order,
                    Order.Status.DRAFT,
                    Order.Status.RESERVED,
                ),
            )
            created_counts["audit_logs"] += int(created)
            audit_ids.add(reserved_audit.id)

            if definition["status"] in {Order.Status.CONFIRMED, Order.Status.SHIPPED}:
                confirmed_audit, created = self._upsert_audit(
                    correlation_id=f"seed:order:{order.order_number}:confirmed",
                    actor=actor,
                    action=AuditLog.Action.ORDER_CONFIRMED,
                    target=order,
                    metadata=self._order_audit_metadata(
                        order,
                        Order.Status.RESERVED,
                        Order.Status.CONFIRMED,
                    ),
                )
                created_counts["audit_logs"] += int(created)
                audit_ids.add(confirmed_audit.id)
            elif definition["status"] == Order.Status.CANCELLED:
                cancelled_audit, created = self._upsert_audit(
                    correlation_id=f"seed:order:{order.order_number}:cancelled",
                    actor=actor,
                    action=AuditLog.Action.ORDER_CANCELLED,
                    target=order,
                    metadata=self._order_audit_metadata(
                        order,
                        Order.Status.RESERVED,
                        Order.Status.CANCELLED,
                        extra={
                            "source": "manual",
                            "reason": "Seeded cancelled order scenario.",
                        },
                    ),
                )
                created_counts["audit_logs"] += int(created)
                audit_ids.add(cancelled_audit.id)

        return audit_ids

    def _upsert_audit(
        self,
        *,
        correlation_id,
        actor,
        action,
        target,
        metadata,
    ):
        audit = (
            AuditLog.objects.filter(correlation_id=correlation_id)
            .order_by("id")
            .first()
        )
        created = audit is None
        values = {
            "actor": actor,
            "action": action,
            "target_model": target.__class__.__name__,
            "target_object_id": str(target.pk),
            "target_repr": str(target),
            "metadata": metadata,
        }
        if created:
            audit = AuditLog.objects.create(
                correlation_id=correlation_id,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(audit, field, value)
            audit.save(update_fields=list(values))
        return audit, created

    def _order_audit_metadata(
        self,
        order,
        status_before,
        status_after,
        extra=None,
    ):
        metadata = {
            "source": "seed_data",
            "order_number": order.order_number,
            "status": {"before": status_before, "after": status_after},
            "total_amount": str(order.total_amount),
            "items": [
                {
                    "product_id": item.product_id,
                    "product_sku": item.product.sku,
                    "warehouse_id": item.warehouse_id,
                    "warehouse_code": item.warehouse.code,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "subtotal": str(item.subtotal),
                }
                for item in order.items.select_related("product", "warehouse")
            ],
        }
        if extra:
            metadata.update(extra)
        return metadata

    def _movement_types_for_status(self, status):
        if status == Order.Status.RESERVED:
            return (StockMovement.MovementType.RESERVATION,)
        if status in {Order.Status.CONFIRMED, Order.Status.SHIPPED}:
            return (
                StockMovement.MovementType.RESERVATION,
                StockMovement.MovementType.STOCK_OUT,
            )
        if status == Order.Status.CANCELLED:
            return (
                StockMovement.MovementType.RESERVATION,
                StockMovement.MovementType.RESERVATION_RELEASE,
            )
        return ()

    def _movement_description(self, order, movement_type):
        if movement_type == StockMovement.MovementType.RESERVATION:
            return f"Reserved for seeded order {order.order_number}"
        if movement_type == StockMovement.MovementType.STOCK_OUT:
            return f"Confirmed seeded order {order.order_number}"
        return f"Released reservation for seeded order {order.order_number}"

    def _write_summary(
        self,
        *,
        inventories,
        orders,
        movement_count,
        audit_count,
        created_counts,
        password_states,
    ):
        status_counts = Counter(order.status for order in orders.values())
        mechanical = inventories[("MECH-KB-001", "MAIN")]
        usb_hub = inventories[("USBC-HUB-001", "MAIN")]

        self.stdout.write(self.style.SUCCESS("StockFlow seed data is ready."))
        self.stdout.write(
            "Seed dataset: "
            f"products={len(PRODUCT_DEFINITIONS)}, "
            f"warehouses={len(WAREHOUSE_DEFINITIONS)}, "
            f"inventories={len(inventories)}, "
            f"orders={len(orders)}, "
            f"stock_movements={movement_count}, "
            f"audit_logs={audit_count}"
        )
        self.stdout.write(
            "Order statuses: "
            + ", ".join(
                f"{status}={status_counts[status]}"
                for status in Order.Status.values
            )
        )
        self.stdout.write(
            "Created this run: "
            + ", ".join(
                f"{name}={created_counts[name]}"
                for name in (
                    "users",
                    "warehouses",
                    "products",
                    "inventories",
                    "orders",
                    "order_items",
                    "stock_movements",
                    "audit_logs",
                )
            )
        )
        self.stdout.write(
            "Scenario A: Mechanical Keyboard @ MAIN "
            f"quantity={mechanical.quantity}, "
            f"reserved={mechanical.reserved_quantity}, "
            f"available={mechanical.available_quantity}"
        )
        self.stdout.write(
            "Scenario B: USB-C Hub @ MAIN "
            f"quantity={usb_hub.quantity}, "
            f"reserved={usb_hub.reserved_quantity}, "
            f"available={usb_hub.available_quantity}"
        )
        self.stdout.write("Scenario C: SEED-ORD-CANCEL is reserved and cancellable.")
        self.stdout.write(
            "Scenario D: SEED-ORD-INSUFFICIENT is a draft multi-item order."
        )
        self.stdout.write(
            "Scenario E: SEED-ORD-EXPIRED is reserved more than 30 minutes ago."
        )
        self.stdout.write("Demo users:")
        for username, state in password_states.items():
            self.stdout.write(f"  {username}: {state}")
