
import os
import csv
import io
from datetime import date, datetime, timedelta
from functools import wraps

import qrcode
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_file, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash


# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

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


# --------------------------------------------------
# DATABASE MODELS
# --------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    products = db.relationship(
        "Product", backref="business", lazy=True,
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
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
        return "Safe"


# --------------------------------------------------
# LOGIN MANAGER
# --------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# --------------------------------------------------
# BUSINESS REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        business_name = request.form.get(
            "business_name", ""
        ).strip()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not business_name or not email or not password:
            flash("Please fill all required fields.", "danger")

        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")

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

            flash("Business registered successfully. Please login.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
@login_required
def logout():

    logout_user()
    flash("You have been logged out.", "info")

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).all()

    total_products = len(products)

    total_stock = sum(p.quantity for p in products)

    expired_count = sum(
        1 for p in products if p.days_left < 0
    )

    expiring_count = sum(
        1 for p in products if 0 <= p.days_left <= 3
    )

    recent_products = sorted(
        products,
        key=lambda p: p.created_at or datetime.min,
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
        products=recent_products,
        category_totals=category_totals
    )


# --------------------------------------------------
# INVENTORY MANAGEMENT
# --------------------------------------------------

@app.route("/inventory")
@login_required
def inventory():

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    query = Product.query.filter_by(user_id=current_user.id)

    if search:
        query = query.filter(
            Product.name.ilike(f"%{search}%")
        )

    if category:
        query = query.filter_by(category=category)

    products = query.order_by(Product.id.desc()).all()

    categories = [
        "Vegetables", "Fruits", "Dairy",
        "Grains", "Meat", "Other"
    ]

    return render_template(
        "inventory.html",
        products=products,
        categories=categories,
        search=search,
        selected_category=category
    )


# --------------------------------------------------
# ADD PRODUCT
# --------------------------------------------------

@app.route("/inventory/add", methods=["GET", "POST"])
@login_required
def add_product():

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

            if not name or not category:
                raise ValueError("Product name and category are required.")

            if quantity <= 0 or price < 0:
                raise ValueError("Enter a valid quantity and price.")

            product = Product(
                name=name,
                category=category,
                quantity=quantity,
                price=price,
                expiry_date=expiry_date,
                user_id=current_user.id
            )

            db.session.add(product)
            db.session.commit()

            flash("Product added successfully!", "success")
            return redirect(url_for("inventory"))

        except (ValueError, TypeError) as error:
            flash(f"Invalid product details: {error}", "danger")

    categories = [
        "Vegetables", "Fruits", "Dairy",
        "Grains", "Meat", "Other"
    ]

    return render_template(
        "product_form.html",
        product=None,
        categories=categories
    )


# --------------------------------------------------
# EDIT PRODUCT
# --------------------------------------------------

@app.route("/inventory/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    if request.method == "POST":

        try:
            product.name = request.form.get("name", "").strip()
            product.category = request.form.get("category", "").strip()
            product.quantity = float(request.form.get("quantity", 0))
            product.price = float(request.form.get("price", 0))
            product.expiry_date = datetime.strptime(
                request.form.get("expiry_date", ""),
                "%Y-%m-%d"
            ).date()

            if not product.name or not product.category:
                raise ValueError("Name and category are required.")

            if product.quantity <= 0 or product.price < 0:
                raise ValueError("Invalid quantity or price.")

            db.session.commit()

            flash("Product updated successfully!", "success")
            return redirect(url_for("inventory"))

        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(f"Invalid product details: {error}", "danger")

    categories = [
        "Vegetables", "Fruits", "Dairy",
        "Grains", "Meat", "Other"
    ]

    return render_template(
        "product_form.html",
        product=product,
        categories=categories
    )


# --------------------------------------------------
# DELETE PRODUCT
# --------------------------------------------------

@app.route("/inventory/delete/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    db.session.delete(product)
    db.session.commit()

    flash("Product deleted successfully.", "success")

    return redirect(url_for("inventory"))


# --------------------------------------------------
# EXPIRY TRACKING
# --------------------------------------------------

@app.route("/expiry")
@login_required
def expiry():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).order_by(Product.expiry_date).all()

    expired = [p for p in products if p.days_left < 0]

    expiring = [
        p for p in products if 0 <= p.days_left <= 3
    ]

    safe = [p for p in products if p.days_left > 3]

    return render_template(
        "expiry.html",
        expired=expired,
        expiring=expiring,
        safe=safe
    )


# --------------------------------------------------
# CSV BULK UPLOAD
# --------------------------------------------------

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
                "Product", "Category", "Quantity (kg)",
                "Price (₹/kg)", "Expiry Date"
            ]

            if not reader.fieldnames or not all(
                col in reader.fieldnames for col in required_columns
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
                    row["Expiry Date"].strip(), "%Y-%m-%d"
                ).date()

                if quantity <= 0 or price < 0:
                    raise ValueError(
                        f"Row {row_number}: Invalid quantity or price."
                    )

                new_products.append(
                    Product(
                        name=name,
                        category=category,
                        quantity=quantity,
                        price=price,
                        expiry_date=expiry_date,
                        user_id=current_user.id
                    )
                )

            if not new_products:
                raise ValueError("The CSV file contains no product records.")

            db.session.add_all(new_products)
            db.session.commit()

            flash(
                f"{len(new_products)} products imported successfully!",
                "success"
            )

        except (ValueError, KeyError, UnicodeDecodeError) as error:
            db.session.rollback()
            flash(f"CSV validation failed: {error}", "danger")

        except Exception:
            db.session.rollback()
            flash("Unable to process the CSV file.", "danger")

        return redirect(url_for("inventory"))

    return render_template("upload.html")


# --------------------------------------------------
# DOWNLOAD INVENTORY CSV
# --------------------------------------------------

@app.route("/download")
@login_required
def download_csv():

    products = Product.query.filter_by(
        user_id=current_user.id
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Product", "Category", "Quantity (kg)",
        "Price (₹/kg)", "Expiry Date"
    ])

    for p in products:
        writer.writerow([
            p.name, p.category, p.quantity,
            p.price, p.expiry_date
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


# --------------------------------------------------
# PRODUCT QR CODE
# --------------------------------------------------

@app.route("/qr/<int:product_id>")
@login_required
def product_qr(product_id):

    product = Product.query.filter_by(
        id=product_id,
        user_id=current_user.id
    ).first_or_404()

    qr_content = (
        f"Product: {product.name}\n"
        f"Category: {product.category}\n"
        f"Quantity: {product.quantity} kg\n"
        f"Expiry: {product.expiry_date}"
    )

    qr = qrcode.make(qr_content)

    image_file = io.BytesIO()
    qr.save(image_file, format="PNG")
    image_file.seek(0)

    return send_file(
        image_file,
        mimetype="image/png",
        download_name=f"product_{product.id}_qr.png"
    )


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(413)
def file_too_large(error):
    flash("File is too large. Maximum upload size is 10 MB.", "danger")
    return redirect(url_for("upload_csv"))


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

with app.app_context():
    db.create_all()


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
