
import os
import csv
import io
from datetime import date, datetime

import qrcode

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, jsonify
)

from flask_sqlalchemy import SQLAlchemy

from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)

from werkzeug.security import (
    generate_password_hash, check_password_hash
)


# ==================================================
# 1. APPLICATION CONFIGURATION
# ==================================================

app = Flask(__name__, instance_relative_config=True)

os.makedirs(app.instance_path, exist_ok=True)
os.makedirs("uploads", exist_ok=True)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "change-this-development-secret-key"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(app.instance_path, "freshtrack.db")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to continue."


# ==================================================
# 2. DATABASE MODELS
# ==================================================

class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    business_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    products = db.relationship(
        "Product",
        backref="business",
        lazy=True,
        cascade="all, delete-orphan"
    )

    transactions = db.relationship(
        "Transaction",
        backref="business",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)

    barcode = db.Column(
        db.String(100),
        nullable=True,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    @property
    def days_left(self):
        return (self.expiry_date - date.today()).days

    @property
    def expiry_status(self):

        if self.days_left < 0:
            return "Expired"

        elif self.days_left <= 3:
            return "Expiring Soon"

        return "Fresh"


class Transaction(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    action = db.Column(db.String(30), nullable=False)
    product_name = db.Column(db.String(120), nullable=False)
    details = db.Column(db.String(500), nullable=False)

    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )


def record_transaction(action, product, details):

    transaction = Transaction(
        action=action,
        product_name=product.name,
        details=details,
        user_id=current_user.id
    )

    db.session.add(transaction)


# ==================================================
# 3. LOGIN MANAGER
# ==================================================

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ==================================================
# 4. HOME PAGE
# ==================================================

@app.route("/")
def home():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# ==================================================
# 5. BUSINESS REGISTRATION
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        business_name = request.form.get(
            "business_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not business_name or not email or not password:

            flash("Please fill all required fields.", "danger")

        elif len(password) < 8:

            flash(
                "Password must contain at least 8 characters.",
                "danger"
            )

        elif password != confirm_password:

            flash("Passwords do not match.", "danger")

        elif User.query.filter_by(email=email).first():

            flash("This email is already registered.", "danger")

        else:

            user = User(
                business_name=business_name,
                email=email
            )

            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            flash(
                "Business registered successfully. Please login.",
                "success"
            )

            return redirect(url_for("login"))

    return render_template("register.html")


# ==================================================
# 6. LOGIN
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):

            login_user(user)

            flash("Login successful!", "success")

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


# ==================================================
# 7. LOGOUT
# ==================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    flash("You have been logged out.", "info")

    return redirect(url_for("login"))


# ==================================================
# 8. DASHBOARD
# ==================================================

@app.route("/dashboard")
@login_required
def dashboard():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).all()

    total_products = len(products)

    total_stock = sum(
        product.quantity for product in products
    )

    expired_count = sum(
        1 for product in products
        if product.days_left < 0
    )

    expiring_count = sum(
        1 for product in products
        if 0 <= product.days_left <= 3
    )

    recent_products = sorted(
        products,
        key=lambda product: product.created_at or datetime.min,
        reverse=True
    )[:5]

    category_totals = {}

    for product in products:

        category_totals[product.category] = (
            category_totals.get(product.category, 0)
            + product.quantity
        )

    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_stock=round(total_stock, 2),
        expired_count=expired_count,
        expiring_count=expiring_count,
        recent_products=recent_products,
        category_totals=category_totals
    )


# ==================================================
# 9. INVENTORY MANAGEMENT
# ==================================================

@app.route("/inventory")
@login_required
def inventory():

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    query = Product.query.filter_by(
        user_id=current_user.id
    )

    if search:
        query = query.filter(
            Product.name.ilike(f"%{search}%")
        )

    if category:
        query = query.filter_by(category=category)

    products = query.order_by(Product.id.desc()).all()

    categories = [
        "Vegetables", "Fruits", "Dairy", "Grains",
        "Meat", "Bakery", "Other"
    ]

    return render_template(
        "inventory.html",
        products=products,
        categories=categories,
        search=search,
        selected_category=category
    )


# ==================================================
# 10. ADD PRODUCT
# ==================================================

@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_product():

    categories = [
        "Vegetables", "Fruits", "Dairy", "Grains",
        "Meat", "Bakery", "Other"
    ]

    if request.method == "POST":

        try:

            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()

            quantity = float(request.form.get("quantity", 0))
            price = float(request.form.get("price", 0))

            expiry_date = datetime.strptime(
                request.form.get("expiry_date", ""),
                "%Y-%m-%d"
            ).date()

            barcode = request.form.get("barcode", "").strip() or None

            if not name or not category:
                raise ValueError(
                    "Product name and category are required."
                )

            if quantity <= 0 or price < 0:
                raise ValueError(
                    "Enter a valid quantity and price."
                )

            if barcode and Product.query.filter_by(
                user_id=current_user.id,
                barcode=barcode
            ).first():

                raise ValueError(
                    "This barcode is already assigned to another product."
                )

            product = Product(
                name=name,
                category=category,
                quantity=quantity,
                price=price,
                expiry_date=expiry_date,
                barcode=barcode,
                user_id=current_user.id
            )

            db.session.add(product)

            record_transaction(
                "Added",
                product,
                (
                    f"Added {quantity:g} kg at ₹{price:g} per kg. "
                    f"Expiry: {expiry_date}. Barcode: {barcode or 'Not provided'}"
                )
            )

            db.session.commit()

            flash("Product added successfully!", "success")

            return redirect(url_for("inventory"))

        except (ValueError, TypeError) as error:

            db.session.rollback()

            flash(
                f"Invalid product details: {error}",
                "danger"
            )

    return render_template(
        "product_form.html",
        product=None,
        categories=categories
    )


# ==================================================
# 11. EDIT PRODUCT
# ==================================================

@app.route("/inventory/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    categories = [
        "Vegetables", "Fruits", "Dairy", "Grains",
        "Meat", "Bakery", "Other"
    ]

    if request.method == "POST":

        try:

            old_name = product.name
            old_quantity = product.quantity
            old_price = product.price
            old_expiry = product.expiry_date
            old_barcode = product.barcode

            new_name = request.form.get("name", "").strip()
            new_category = request.form.get("category", "").strip()

            new_quantity = float(request.form.get("quantity", 0))
            new_price = float(request.form.get("price", 0))

            new_expiry = datetime.strptime(
                request.form.get("expiry_date", ""),
                "%Y-%m-%d"
            ).date()

            new_barcode = request.form.get("barcode", "").strip() or None

            if not new_name or not new_category:
                raise ValueError("Name and category are required.")

            if new_quantity <= 0 or new_price < 0:
                raise ValueError("Invalid quantity or price.")

            if new_barcode and Product.query.filter(
                Product.user_id == current_user.id,
                Product.barcode == new_barcode,
                Product.id != product.id
            ).first():

                raise ValueError(
                    "This barcode is already assigned to another product."
                )

            product.name = new_name
            product.category = new_category
            product.quantity = new_quantity
            product.price = new_price
            product.expiry_date = new_expiry
            product.barcode = new_barcode

            record_transaction(
                "Updated",
                product,
                (
                    f"Name: {old_name} → {new_name}; "
                    f"Quantity: {old_quantity:g} → {new_quantity:g} kg; "
                    f"Price: ₹{old_price:g} → ₹{new_price:g}; "
                    f"Expiry: {old_expiry} → {new_expiry}; "
                    f"Barcode: {old_barcode or 'None'} → {new_barcode or 'None'}"
                )
            )

            db.session.commit()

            flash("Product updated successfully!", "success")

            return redirect(url_for("inventory"))

        except (ValueError, TypeError) as error:

            db.session.rollback()

            flash(
                f"Invalid product details: {error}",
                "danger"
            )

    return render_template(
        "product_form.html",
        product=product,
        categories=categories
    )


# ==================================================
# 12. DELETE PRODUCT
# ==================================================

@app.route("/inventory/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    record_transaction(
        "Deleted",
        product,
        (
            f"Deleted product. Quantity: {product.quantity:g} kg; "
            f"Price: ₹{product.price:g}; "
            f"Expiry: {product.expiry_date}; "
            f"Barcode: {product.barcode or 'None'}"
        )
    )

    db.session.delete(product)
    db.session.commit()

    flash("Product deleted successfully.", "success")

    return redirect(url_for("inventory"))


# ==================================================
# 13. EXPIRY TRACKING
# ==================================================

@app.route("/expiry")
@login_required
def expiry():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).order_by(Product.expiry_date).all()

    expired = [
        product for product in products
        if product.days_left < 0
    ]

    expiring = [
        product for product in products
        if 0 <= product.days_left <= 3
    ]

    safe = [
        product for product in products
        if product.days_left > 3
    ]

    return render_template(
        "expiry.html",
        expired_products=expired,
        expiring_products=expiring,
        fresh_products=safe
    )


# ==================================================
# 14. CSV BULK UPLOAD
# ==================================================

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_csv():

    if request.method == "POST":

        file = request.files.get("file")

        if not file or not file.filename.lower().endswith(".csv"):

            flash("Please select a valid CSV file.", "danger")

            return redirect(url_for("upload_csv"))

        try:

            content = file.stream.read().decode("utf-8-sig")

            reader = csv.DictReader(io.StringIO(content))

            required_columns = [
                "Product",
                "Category",
                "Quantity (kg)",
                "Price (₹/kg)",
                "Expiry Date"
            ]

            if not reader.fieldnames or not all(
                column in reader.fieldnames
                for column in required_columns
            ):

                flash(
                    "CSV must contain: " + ", ".join(required_columns),
                    "danger"
                )

                return redirect(url_for("upload_csv"))

            new_products = []

            for row_number, row in enumerate(reader, start=2):

                name = (row.get("Product") or "").strip()
                category = (row.get("Category") or "").strip()

                if not name or not category:
                    raise ValueError(
                        f"Row {row_number}: Product and Category are required."
                    )

                quantity = float(row["Quantity (kg)"])
                price = float(row["Price (₹/kg)"])

                expiry_date = datetime.strptime(
                    row["Expiry Date"].strip(),
                    "%Y-%m-%d"
                ).date()

                barcode = (row.get("Barcode") or "").strip() or None

                if quantity <= 0 or price < 0:
                    raise ValueError(
                        f"Row {row_number}: Invalid quantity or price."
                    )

                if barcode and Product.query.filter_by(
                    user_id=current_user.id,
                    barcode=barcode
                ).first():

                    raise ValueError(
                        f"Row {row_number}: Barcode {barcode} already exists."
                    )

                new_products.append(
                    Product(
                        name=name,
                        category=category,
                        quantity=quantity,
                        price=price,
                        expiry_date=expiry_date,
                        barcode=barcode,
                        user_id=current_user.id
                    )
                )

            if not new_products:
                raise ValueError(
                    "The CSV file contains no product records."
                )

            db.session.add_all(new_products)

            for product in new_products:
                record_transaction(
                    "Imported",
                    product,
                    (
                        f"Imported through CSV. Quantity: {product.quantity:g} kg; "
                        f"Barcode: {product.barcode or 'None'}"
                    )
                )

            db.session.commit()

            flash(
                f"{len(new_products)} products imported successfully!",
                "success"
            )

        except (
            ValueError, KeyError, UnicodeDecodeError
        ) as error:

            db.session.rollback()

            flash(
                f"CSV validation failed: {error}",
                "danger"
            )

        except Exception:

            db.session.rollback()

            flash("Unable to process the CSV file.", "danger")

        return redirect(url_for("inventory"))

    return render_template("upload.html")


# ==================================================
# 15. DOWNLOAD INVENTORY CSV
# ==================================================

@app.route("/download")
@login_required
def download_csv():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).all()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Product",
        "Category",
        "Quantity (kg)",
        "Price (₹/kg)",
        "Expiry Date",
        "Barcode"
    ])

    for product in products:

        writer.writerow([
            product.name,
            product.category,
            product.quantity,
            product.price,
            product.expiry_date,
            product.barcode or ""
        ])

    memory_file = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )

    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name="freshtrack_inventory.csv"
    )


# ==================================================
# 16. POS-READY SALES MANAGEMENT
# ==================================================

@app.route("/sell/<int:product_id>", methods=["POST"])
@login_required
def sell_product(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    try:

        sold_quantity = float(
            request.form.get("quantity", 0)
        )

        if sold_quantity <= 0:
            raise ValueError(
                "Enter a valid sale quantity."
            )

        if sold_quantity > product.quantity:
            raise ValueError(
                "Insufficient stock available."
            )

        if product.days_left < 0:
            raise ValueError(
                "Expired products cannot be sold."
            )

        total_amount = sold_quantity * product.price

        product.quantity -= sold_quantity

        record_transaction(
            "Sold",
            product,
            (
                f"Sold {sold_quantity:g} kg at "
                f"₹{product.price:g} per kg. "
                f"Total amount: ₹{total_amount:.2f}. "
                f"Remaining stock: {product.quantity:g} kg."
            )
        )

        db.session.commit()

        flash(
            f"Sale recorded successfully! Total: ₹{total_amount:.2f}",
            "success"
        )

    except (ValueError, TypeError) as error:

        db.session.rollback()

        flash(
            f"Sale failed: {error}",
            "danger"
        )

    return redirect(url_for("inventory"))


# ==================================================
# 17. TRANSACTION HISTORY
# ==================================================

@app.route("/transactions")
@login_required
def transactions():

    transaction_list = Transaction.query.filter_by(
        user_id=current_user.id
    ).order_by(
        Transaction.timestamp.desc()
    ).all()

    return render_template(
        "transactions.html",
        transactions=transaction_list
    )


# ==================================================
# 18. QR CODE GENERATION
# ==================================================

@app.route("/qr/<int:product_id>")
@login_required
def product_qr(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    product_url = url_for(
        "product_details",
        product_id=product.id,
        _external=True
    )

    qr = qrcode.make(product_url)

    image_file = io.BytesIO()

    qr.save(image_file, format="PNG")

    image_file.seek(0)

    return send_file(
        image_file,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"product_{product.id}_qr.png"
    )


# ==================================================
# 19. PRODUCT DETAILS PAGE
# ==================================================

@app.route("/product/<int:product_id>")
@login_required
def product_details(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    return render_template(
        "product_details.html",
        product=product
    )


# ==================================================
# 20. BARCODE SCANNER PAGE
# ==================================================

@app.route("/scan")
@login_required
def scan_barcode():

    return render_template("scan_barcode.html")


# ==================================================
# 21. BARCODE LOOKUP API
# ==================================================

@app.route("/barcode/<string:barcode>")
@login_required
def barcode_lookup(barcode):

    product = Product.query.filter_by(
        barcode=barcode,
        user_id=current_user.id
    ).first()

    if not product:

        return jsonify({
            "success": False,
            "message": "No product found for this barcode."
        }), 404

    return jsonify({
        "success": True,
        "product": {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "quantity": product.quantity,
            "price": product.price,
            "expiry_date": product.expiry_date.strftime("%Y-%m-%d"),
            "barcode": product.barcode,
            "expiry_status": product.expiry_status,
            "details_url": url_for(
                "product_details",
                product_id=product.id
            )
        }
    })


# ==================================================
# 22. ERROR HANDLERS
# ==================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(413)
def file_too_large(error):

    flash(
        "File is too large. Maximum upload size is 10 MB.",
        "danger"
    )

    return redirect(url_for("upload_csv"))


# ==================================================
# 23. DATABASE INITIALIZATION AND MIGRATION
# ==================================================

with app.app_context():

    db.create_all()

    columns = db.session.execute(
        db.text("PRAGMA table_info(product)")
    ).fetchall()

    column_names = [column[1] for column in columns]

    if "barcode" not in column_names:

        db.session.execute(
            db.text("ALTER TABLE product ADD COLUMN barcode VARCHAR(100)")
        )

        db.session.commit()

        print("Database updated: barcode column added.")


# ==================================================
# 24. RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
