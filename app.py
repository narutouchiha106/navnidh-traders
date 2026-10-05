import os, re, uuid, hashlib
from datetime import datetime
from functools import wraps
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv('SECRET_KEY', 'dev-change-me'),
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///navnidh.db'),
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    UPLOAD_DIR=os.path.join(app.root_path, 'static', 'uploads'))
db = SQLAlchemy(app)
os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
CSRFProtect(app)
WA = os.getenv('WHATSAPP_NUMBER', '91XXXXXXXXXX')
STATUSES = ['Pending', 'Confirmed', 'Processing', 'Shipped', 'Delivered', 'Cancelled']

# ---------- Models ----------
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(90), unique=True, index=True, nullable=False)
    description = db.Column(db.String(200))
    color = db.Column(db.String(7), default='#8b5e3c')
    products = db.relationship('Product', backref='category')

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    slug = db.Column(db.String(170), unique=True, index=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False, index=True)
    brand = db.Column(db.String(80), default='Navnidh')
    description = db.Column(db.Text)
    specs = db.Column(db.Text)  # one "Label: value" per line
    price = db.Column(db.Integer, nullable=False)
    discount_price = db.Column(db.Integer)
    stock = db.Column(db.Integer, default=10)
    rating = db.Column(db.Float, default=4.5)
    image = db.Column(db.String(200))
    featured = db.Column(db.Boolean, default=False)
    bestseller = db.Column(db.Boolean, default=False)
    is_new = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    @property
    def now_price(self): return self.discount_price or self.price
    @property
    def off(self): return round(100 - self.now_price * 100 / self.price) if self.discount_price else 0
    @property
    def img(self):
        return url_for('static', filename='uploads/' + self.image) if self.image else url_for('chair_svg', color=self.category.color[1:])
    @property
    def spec_list(self):
        return [l.split(':', 1) for l in (self.specs or '').splitlines() if ':' in l]

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    name = db.Column(db.String(100)); phone = db.Column(db.String(15)); email = db.Column(db.String(150))
    address = db.Column(db.String(300)); city = db.Column(db.String(80)); state = db.Column(db.String(80))
    pincode = db.Column(db.String(10)); notes = db.Column(db.String(300))
    payment = db.Column(db.String(40)); status = db.Column(db.String(20), default='Pending', index=True)
    total = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='SET NULL'))
    name = db.Column(db.String(150)); price = db.Column(db.Integer); qty = db.Column(db.Integer)

class Contact(db.Model):
    __tablename__ = 'contacts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100)); email = db.Column(db.String(150)); message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- Helpers ----------
def slugify(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def cart_items():
    out = []
    for pid, qty in session.get('cart', {}).items():
        p = db.session.get(Product, int(pid))
        if p: out.append((p, qty))
    return out

def totals(items):
    sub = sum(p.now_price * q for p, q in items)
    ship = 0 if (sub >= 5000 or sub == 0) else 250
    return sub, ship, sub + ship

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        u = db.session.get(User, session.get('uid', 0))
        if not u or not u.is_admin: return redirect(url_for('login', next=request.path))
        return f(*a, **k)
    return w

@app.context_processor
def inject():
    return dict(cart_count=sum(session.get('cart', {}).values()), nav_cats=Category.query.all(),
                wa_number=WA, user=db.session.get(User, session.get('uid', 0)),
                wa_link=lambda n=None: f"https://wa.me/{WA}?text=" + quote(
                    f"Hello Navnidh Traders, I am interested in {n}. Please share price, availability and delivery details."
                    if n else "Hello Navnidh Traders, I would like to enquire about your chairs."))

@app.route('/img/<color>.svg')
def chair_svg(color):
    color = re.sub(r'[^0-9a-fA-F]', '', color)[:6] or '8b5e3c'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#f4efe9"/>
<ellipse cx="200" cy="350" rx="110" ry="14" fill="#0001"/><rect x="120" y="60" width="160" height="150" rx="40" fill="#{color}"/>
<rect x="105" y="200" width="190" height="45" rx="18" fill="#{color}" opacity=".85"/><rect x="193" y="245" width="14" height="70" fill="#333"/>
<path d="M200 315 L110 345 M200 315 L290 345 M200 315 L200 348" stroke="#333" stroke-width="10" stroke-linecap="round"/></svg>'''
    return Response(svg, mimetype='image/svg+xml', headers={'Cache-Control': 'public, max-age=86400'})

# ---------- Storefront ----------
@app.route('/')
def index():
    return render_template('index.html', cats=Category.query.all(),
        featured=Product.query.filter_by(featured=True).limit(8).all(),
        best=Product.query.filter_by(bestseller=True).limit(4).all())

@app.route('/shop')
def shop():
    a = request.args
    q = Product.query.join(Category)
    s = a.get('q', '').strip()
    if s:
        l = f'%{s}%'
        q = q.filter(db.or_(Product.name.ilike(l), Product.description.ilike(l), Product.specs.ilike(l),
                            Product.brand.ilike(l), Category.name.ilike(l)))
    if a.get('category'): q = q.filter(Category.slug == a['category'])
    if a.get('max', type=int): q = q.filter(Product.price <= a.get('max', type=int))
    if a.get('rating', type=float): q = q.filter(Product.rating >= a.get('rating', type=float))
    if a.get('instock'): q = q.filter(Product.stock > 0)
    order = {'new': Product.created_at.desc(), 'low': Product.price.asc(), 'high': Product.price.desc(),
             'rating': Product.rating.desc()}.get(a.get('sort'), Product.bestseller.desc())
    pg = q.order_by(order, Product.id).paginate(page=a.get('page', 1, type=int), per_page=12, error_out=False)
    args = {k: v for k, v in a.items() if k != 'page' and v}
    return render_template('shop.html', pg=pg, args=args, cats=Category.query.all())

@app.route('/category/<slug>')
def category(slug):
    get_or_404 = Category.query.filter_by(slug=slug).first_or_404()
    return redirect(url_for('shop', category=get_or_404.slug))

@app.route('/product/<slug>')
def product(slug):
    p = Product.query.filter_by(slug=slug).first_or_404()
    rel = Product.query.filter(Product.category_id == p.category_id, Product.id != p.id).limit(4).all()
    return render_template('product.html', p=p, rel=rel)

@app.route('/api/suggest')
def suggest():
    s = request.args.get('q', '').strip()
    if len(s) < 2: return jsonify([])
    return jsonify([p.name for p in Product.query.filter(Product.name.ilike(f'%{s}%')).limit(6)])

@app.route('/cart')
def cart():
    items = cart_items()
    return render_template('cart.html', items=items, t=totals(items))

@app.route('/cart/add/<int:pid>', methods=['POST'])
def cart_add(pid):
    p = db.get_or_404(Product, pid)
    qty = max(1, min(request.form.get('qty', 1, type=int), 20))
    if p.stock < 1:
        flash('Sorry, this item is out of stock.', 'danger'); return redirect(request.referrer or url_for('shop'))
    c = session.get('cart', {}); c[str(pid)] = min(c.get(str(pid), 0) + qty, p.stock)
    session['cart'] = c
    flash(f'{p.name} added to cart.', 'success')
    if request.form.get('buy'): return redirect(url_for('checkout'))
    return redirect(request.referrer or url_for('cart'))

@app.route('/cart/update/<int:pid>', methods=['POST'])
def cart_update(pid):
    c = session.get('cart', {}); qty = request.form.get('qty', 1, type=int)
    if qty <= 0: c.pop(str(pid), None)
    elif str(pid) in c: c[str(pid)] = min(qty, 20)
    session['cart'] = c
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    items = cart_items()
    if not items:
        flash('Your cart is empty.', 'warning'); return redirect(url_for('shop'))
    t = totals(items); f = request.form
    if request.method == 'POST':
        err = []
        for k in ('name', 'address', 'city', 'state'):
            if not f.get(k, '').strip(): err.append(f'{k.title()} is required.')
        if not re.fullmatch(r'[6-9]\d{9}', f.get('phone', '')): err.append('Enter a valid 10-digit mobile number.')
        if not re.fullmatch(r'\d{6}', f.get('pincode', '')): err.append('Enter a valid 6-digit pincode.')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', f.get('email', '')): err.append('Enter a valid email.')
        if err:
            for e in err: flash(e, 'danger')
            return render_template('checkout.html', items=items, t=t, f=f)
        o = Order(user_id=session.get('uid'), name=f['name'][:100], phone=f['phone'], email=f['email'][:150],
                  address=f['address'][:300], city=f['city'][:80], state=f['state'][:80], pincode=f['pincode'],
                  notes=f.get('notes', '')[:300], total=t[2],
                  payment='Online Payment (pending gateway)' if f.get('payment') == 'online' else 'Cash on Delivery')
        for p, q in items:
            o.items.append(OrderItem(product_id=p.id, name=p.name, price=p.now_price, qty=q))
            p.stock = max(0, p.stock - q)
        db.session.add(o); db.session.commit(); session['cart'] = {}
        return redirect(url_for('order_done', oid=o.id))
    return render_template('checkout.html', items=items, t=t, f=f)

@app.route('/order/<int:oid>/thanks')
def order_done(oid): return render_template('thanks.html', o=db.get_or_404(Order, oid))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        f = request.form
        if f.get('name', '').strip() and f.get('message', '').strip():
            db.session.add(Contact(name=f['name'][:100], email=f.get('email', '')[:150], message=f['message'][:2000]))
            db.session.commit(); flash('Thank you! We will get back to you soon.', 'success')
            return redirect(url_for('contact'))
        flash('Please enter your name and message.', 'danger')
    return render_template('contact.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email', '').lower().strip()).first()
        if u and check_password_hash(u.password_hash, request.form.get('password', '')):
            cart = session.get('cart', {}); session.clear(); session['uid'] = u.id; session['cart'] = cart
            return redirect(url_for('admin') if u.is_admin else url_for('index'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', mode='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        f = request.form; email = f.get('email', '').lower().strip()
        if not f.get('name', '').strip() or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(f.get('password', '')) < 8:
            flash('Enter name, valid email and a password of 8+ characters.', 'danger')
        elif User.query.filter_by(email=email).first(): flash('Email already registered.', 'danger')
        else:
            u = User(name=f['name'][:100], email=email, password_hash=generate_password_hash(f['password']))
            db.session.add(u); db.session.commit(); session['uid'] = u.id
            return redirect(url_for('index'))
    return render_template('login.html', mode='register')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/robots.txt')
def robots(): return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {url_for('sitemap', _external=True)}\n", mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    urls = [url_for(e, _external=True) for e in ('index', 'shop', 'about', 'contact')]
    urls += [url_for('product', slug=p.slug, _external=True) for p in Product.query.all()]
    x = ''.join(f'<url><loc>{u}</loc></url>' for u in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{x}</urlset>', mimetype='application/xml')

@app.errorhandler(404)
def nf(e): return render_template('404.html'), 404

@app.errorhandler(500)
def ise(e): return render_template('404.html', server=True), 500

# ---------- Admin ----------
@app.route('/admin')
@admin_required
def admin():
    paid = db.session.query(db.func.coalesce(db.func.sum(Order.total), 0)).filter(Order.status != 'Cancelled').scalar()
    s = dict(Products=Product.query.count(), Orders=Order.query.count(),
             Pending=Order.query.filter_by(status='Pending').count(),
             Completed=Order.query.filter_by(status='Delivered').count(),
             Customers=User.query.filter_by(is_admin=False).count(), Revenue='₹{:,}'.format(paid))
    return render_template('admin/dashboard.html', s=s, recent=Order.query.order_by(Order.id.desc()).limit(5).all())

@app.route('/admin/products')
@admin_required
def admin_products(): return render_template('admin/products.html', ps=Product.query.order_by(Product.id.desc()).all())

@app.route('/admin/product/new', methods=['GET', 'POST'])
@app.route('/admin/product/<int:pid>', methods=['GET', 'POST'])
@admin_required
def admin_product(pid=None):
    p = db.get_or_404(Product, pid) if pid else None
    if request.method == 'POST':
        f = request.form
        try:
            name = f['name'].strip(); price = int(f['price']); cid = int(f['category_id'])
            disc = int(f['discount_price']) if f.get('discount_price') else None
            stock = int(f.get('stock') or 0)
            if not name or price <= 0 or (disc and disc >= price): raise ValueError
        except (ValueError, KeyError):
            flash('Please check name, price, discount (must be lower than price) and category.', 'danger')
            return render_template('admin/form.html', p=p, cats=Category.query.all())
        if not p:
            p = Product(slug=slugify(name) + '-' + uuid.uuid4().hex[:4]); db.session.add(p)
        p.name, p.price, p.discount_price, p.stock, p.category_id = name, price, disc, stock, cid
        p.brand = f.get('brand', 'Navnidh')[:80]; p.description = f.get('description'); p.specs = f.get('specs')
        p.featured, p.bestseller, p.is_new = bool(f.get('featured')), bool(f.get('bestseller')), bool(f.get('is_new'))
        up = request.files.get('image')
        if up and up.filename:
            ext = secure_filename(up.filename).rsplit('.', 1)[-1].lower()
            if ext in ('jpg', 'jpeg', 'png', 'webp'):
                fn = uuid.uuid4().hex + '.' + ext; up.save(os.path.join(app.config['UPLOAD_DIR'], fn)); p.image = fn
            else: flash('Image skipped: only JPG, PNG or WEBP allowed.', 'warning')
        db.session.commit(); flash('Product saved.', 'success')
        return redirect(url_for('admin_products'))
    return render_template('admin/form.html', p=p, cats=Category.query.all())

@app.route('/admin/product/<int:pid>/delete', methods=['POST'])
@admin_required
def admin_delete(pid):
    p = db.get_or_404(Product, pid)
    OrderItem.query.filter_by(product_id=pid).update({'product_id': None})
    db.session.delete(p); db.session.commit(); flash('Product deleted.', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/orders')
@admin_required
def admin_orders(): return render_template('admin/orders.html', os=Order.query.order_by(Order.id.desc()).all(), statuses=STATUSES)

@app.route('/admin/order/<int:oid>/status', methods=['POST'])
@admin_required
def admin_status(oid):
    o = db.get_or_404(Order, oid)
    if request.form.get('status') in STATUSES: o.status = request.form['status']; db.session.commit()
    return redirect(url_for('admin_orders'))

# ---------- Seed ----------
def seed():
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        db.session.add(User(name='Admin', email=os.getenv('ADMIN_EMAIL', 'admin@example.com').lower(), is_admin=True,
            password_hash=generate_password_hash(os.getenv('ADMIN_PASSWORD', 'ChangeMe@123'))))
    if not Category.query.first():
        C = [('Office Chairs', '#6b4a33', 'Ergonomic comfort for long workdays'), ('Executive Chairs', '#2f2a26', 'Leather luxury for leaders'),
             ('Gaming Chairs', '#b23a30', 'Racing-style support for gamers'), ('Study Chairs', '#4f7a8a', 'Posture-friendly seating for students'),
             ('Dining Chairs', '#a67c52', 'Elegant seating for family meals'), ('Visitor Chairs', '#5c6b5a', 'Neat and sturdy guest seating'),
             ('Plastic Chairs', '#7d8a99', 'Light, durable and easy to clean'), ('Reception Chairs', '#8a5a6b', 'Welcoming seating for lobbies')]
        cats = {}
        for n, c, d in C:
            cats[n] = Category(name=n, slug=slugify(n), color=c, description=d); db.session.add(cats[n])
        db.session.flush()
        P = [('ErgoMax Mesh Office Chair', 'Office Chairs', 7499, 5999, 'Breathable mesh back, adjustable lumbar support and 3D armrests.', 'Material: Mesh & Nylon\nDimensions: 62 x 60 x 110 cm\nWeight capacity: 120 kg\nWarranty: 1 year'),
             ('ProSeat High-Back Revolving Chair', 'Office Chairs', 4999, 3999, 'Cushioned high-back chair with smooth 360° swivel.', 'Material: PU Leatherette\nDimensions: 58 x 58 x 105 cm\nWeight capacity: 110 kg'),
             ('Regal Executive Leather Chair', 'Executive Chairs', 15999, 12999, 'Premium leather with tilt lock, headrest and chrome base.', 'Material: Genuine Leather\nDimensions: 70 x 70 x 125 cm\nWeight capacity: 150 kg'),
             ('Boardroom Pro Executive Chair', 'Executive Chairs', 11999, None, 'Deep-padded executive seat for long meetings.', 'Material: PU Leather\nDimensions: 68 x 66 x 120 cm\nWeight capacity: 130 kg'),
             ('Velocity Racing Gaming Chair', 'Gaming Chairs', 12499, 9999, 'Reclining gaming chair with neck and lumbar pillows.', 'Material: PU Leather\nDimensions: 66 x 70 x 130 cm\nWeight capacity: 140 kg\nRecline: 90-155°'),
             ('Pulse RGB Gaming Chair', 'Gaming Chairs', 16999, 14499, 'Premium gaming throne with 4D armrests.', 'Material: Fabric & Steel\nWeight capacity: 150 kg'),
             ('Scholar Study Chair', 'Study Chairs', 2999, 2399, 'Height adjustable mid-back chair for desks.', 'Material: Fabric\nDimensions: 50 x 52 x 90 cm\nWeight capacity: 90 kg'),
             ('Junior Posture Study Chair', 'Study Chairs', 3499, None, 'Posture-correct design with curved backrest.', 'Material: Mesh\nWeight capacity: 80 kg'),
             ('Oakline Wooden Dining Chair', 'Dining Chairs', 3999, 3299, 'Solid wood frame with cushioned seat.', 'Material: Sheesham Wood\nDimensions: 45 x 50 x 92 cm\nWeight capacity: 120 kg'),
             ('Classic Visitor Chair', 'Visitor Chairs', 2499, 1999, 'Cantilever frame visitor chair with padded seat.', 'Material: Steel & Fabric\nWeight capacity: 100 kg'),
             ('Everyday Plastic Armchair', 'Plastic Chairs', 899, 749, 'Strong virgin plastic with ergonomic arms.', 'Material: Virgin Plastic\nWeight capacity: 120 kg'),
             ('Lounge Reception Sofa Chair', 'Reception Chairs', 8999, 7499, 'Plush single-seater for lobbies and waiting areas.', 'Material: Fabric & Wood\nDimensions: 75 x 70 x 80 cm\nWeight capacity: 130 kg')]
        for i, (n, c, pr, d, ds, sp) in enumerate(P):
            db.session.add(Product(name=n, slug=slugify(n), category_id=cats[c].id, price=pr, discount_price=d, description=ds, specs=sp,
                stock=0 if i == 3 else 12, rating=round(4 + (i % 10) / 10, 1), featured=True, bestseller=i % 3 == 0, is_new=i % 4 == 0))
    db.session.commit()

@app.cli.command('seed')
def seed_cmd(): seed(); print('Database ready.')

if __name__ == '__main__':
    with app.app_context(): seed()
    app.run(debug=os.getenv('FLASK_DEBUG', '1') == '1')
