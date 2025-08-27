from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import mysql.connector
import json
from mysql.connector import Error
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

import os

# Get the absolute path to the templates directory
template_dir = os.path.abspath('templates')

app = Flask(__name__, template_folder=template_dir)
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key in production

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '0987654321',
    'database': 'pharmacy_management',
    'auth_plugin': 'mysql_native_password'
}

def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please enter both username and password', 'danger')
            return render_template('login.html')
            
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    'SELECT * FROM user WHERE username = %s', 
                    (username,)
                )
                user = cursor.fetchone()
                
                if user and check_password_hash(user['password_hash'], password):
                    session['user_id'] = user['user_id']
                    session['username'] = user['username']
                    session['email'] = user['email']
                    session['is_admin'] = bool(user['is_admin'])
                    
                    flash('Login successful!', 'success')
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard'))
                else:
                    flash('Invalid username or password', 'danger')
                    
            except Error as e:
                flash('An error occurred. Please try again.', 'danger')
                print(f"Database error: {e}")
            finally:
                cursor.close()
                conn.close()
        else:
            flash('Database connection error', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Get counts for dashboard
            cursor.execute('SELECT COUNT(*) as count FROM medicines')
            medicine_count = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM customers')
            customer_count = cursor.fetchone()['count']
            
            # Get recent sales (last 5)
            cursor.execute('''
                SELECT s.sales_id, s.sale_date, c.name as customer_name, s.total_amount 
                FROM sales s 
                LEFT JOIN customers c ON s.phone = c.phone 
                ORDER BY s.sale_date DESC 
                LIMIT 5
            ''')
            recent_sales = cursor.fetchall()
            
            # Get low stock medicines
            cursor.execute('''
                SELECT * FROM medicines 
                WHERE quantity < 10 
                ORDER BY quantity ASC 
                LIMIT 5
            ''')
            low_stock = cursor.fetchall()
            
            return render_template('dashboard.html', 
                                 medicine_count=medicine_count,
                                 customer_count=customer_count,
                                 recent_sales=recent_sales,
                                 low_stock=low_stock,
                                 is_admin=session.get('is_admin', False))
            
        except Error as e:
            flash('Error fetching dashboard data', 'danger')
            print(f"Database error: {e}")
            return render_template('dashboard.html', is_admin=session.get('is_admin', False))
        finally:
            cursor.close()
            conn.close()
    else:
        flash('Database connection error', 'danger')
        return render_template('dashboard.html', is_admin=session.get('is_admin', False))

@app.route('/medicines')
@login_required
def list_medicines():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        search = request.args.get('search', '')
        if search:
            cursor.execute('''
                SELECT * FROM medicines 
                WHERE name LIKE %s OR description LIKE %s OR manufacturer LIKE %s
                ORDER BY name
            ''', (f'%{search}%', f'%{search}%', f'%{search}%'))
        else:
            cursor.execute('SELECT * FROM medicines ORDER BY name')
            
        medicines = cursor.fetchall()
        return render_template('medicines/list.html', medicines=medicines, search=search)
        
    except Error as e:
        flash(f'Error retrieving medicines: {str(e)}', 'danger')
        return render_template('medicines/list.html', medicines=[])
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/medicines/add', methods=['GET', 'POST'])
@login_required
def add_medicine():
    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form.get('description', '')
            price = float(request.form['price'])
            quantity = int(request.form['quantity'])
            manufacturer = request.form.get('manufacturer', '')
            expiry_date = request.form.get('expiry_date')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO medicines (name, description, price, quantity, manufacturer, expiry_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (name, description, price, quantity, manufacturer, expiry_date))
            
            conn.commit()
            flash('Medicine added successfully!', 'success')
            return redirect(url_for('list_medicines'))
            
        except Error as e:
            conn.rollback()
            flash(f'Error adding medicine: {str(e)}', 'danger')
        except ValueError:
            flash('Invalid input values', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    return render_template('medicines/add.html')

@app.route('/medicines/restock', methods=['POST'])
@login_required
def restock_medicine():
    if request.method == 'POST':
        try:
            medicine_id = request.form['medicine_id']
            quantity = int(request.form['quantity'])
            
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # Get current quantity
            cursor.execute('SELECT quantity FROM medicines WHERE customer_id = %s', (medicine_id,))
            current = cursor.fetchone()
            
            if not current:
                flash('Medicine not found', 'danger')
                return redirect(url_for('list_medicines'))
            
            # Update quantity
            new_quantity = current['quantity'] + quantity
            cursor.execute('''
                UPDATE medicines 
                SET quantity = %s 
                WHERE customer_id = %s
            ''', (new_quantity, medicine_id))
            
            conn.commit()
            flash(f'Successfully added {quantity} items to stock', 'success')
            
        except Error as e:
            conn.rollback()
            flash(f'Error updating stock: {str(e)}', 'danger')
        except ValueError:
            flash('Invalid quantity', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    return redirect(url_for('list_medicines'))

@app.route('/medicines/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_medicine(id):
    if request.method == 'POST':
        try:
            name = request.form['name']
            description = request.form.get('description', '')
            price = float(request.form['price'])
            quantity = int(request.form['quantity'])
            manufacturer = request.form.get('manufacturer', '')
            expiry_date = request.form.get('expiry_date')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE medicines 
                SET name = %s, description = %s, price = %s, 
                    quantity = %s, manufacturer = %s, expiry_date = %s
                WHERE medicines_id = %s
            ''', (name, description, price, quantity, manufacturer, expiry_date, id))
            
            conn.commit()
            flash('Medicine updated successfully!', 'success')
            return redirect(url_for('list_medicines'))
            
        except Error as e:
            conn.rollback()
            flash(f'Error updating medicine: {str(e)}', 'danger')
        except ValueError:
            flash('Invalid input values', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    # GET request - show edit form
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM medicines WHERE medicines_id = %s', (id,))
        medicine = cursor.fetchone()
        
        if not medicine:
            flash('Medicine not found', 'danger')
            return redirect(url_for('list_medicines'))
            
        return render_template('medicines/edit_new.html', medicine=medicine)
        
    except Error as e:
        flash(f'Error retrieving medicine: {str(e)}', 'danger')
        return redirect(url_for('list_medicines'))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/medicines/delete/<int:id>', methods=['POST'])
@login_required
def delete_medicine(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM medicines WHERE medicines_id = %s', (id,))
        conn.commit()
        
        flash('Medicine deleted successfully', 'success')
        
    except Error as e:
        conn.rollback()
        flash('Error deleting medicine', 'danger')
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    
    return redirect(url_for('list_medicines'))

# Customers Routes

@app.route('/customers')
@login_required
def list_customers():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        search = request.args.get('search', '')
        if search:
            cursor.execute('''
                SELECT * FROM customers 
                WHERE name LIKE %s OR phone LIKE %s OR email LIKE %s
                ORDER BY name
            ''', (f'%{search}%', f'%{search}%', f'%{search}%'))
        else:
            cursor.execute('SELECT * FROM customers ORDER BY name')
            
        customers = cursor.fetchall()
        return render_template('customers/list.html', customers=customers, search=search)
        
    except Error as e:
        flash(f'Error retrieving customers: {str(e)}', 'danger')
        return render_template('customers/list.html', customers=[])
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        try:
            name = request.form['name']
            phone = request.form.get('phone', '')
            email = request.form.get('email', '')
            address = request.form.get('address', '')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO customers (name, phone, email, address)
                VALUES (%s, %s, %s, %s)
            ''', (name, phone, email, address))
            
            conn.commit()
            flash('Customer added successfully!', 'success')
            return redirect(url_for('list_customers'))
            
        except Error as e:
            conn.rollback()
            flash(f'Error adding customer: {str(e)}', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    return render_template('customers/add.html')

@app.route('/customers/<int:id>')
@login_required
def view_customer(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get customer details
        cursor.execute('SELECT * FROM customers WHERE customer_id = %s', (id,))
        customer = cursor.fetchone()
        
        if not customer:
            flash('Customer not found', 'danger')
            return redirect(url_for('list_customers'))
        
        # Get customer's purchase history
        cursor.execute('''
            SELECT s.sales_id, s.sale_date, s.total_amount, COUNT(si.id) as item_count
            FROM sales s
            LEFT JOIN sale_items si ON s.sales_id = si.sales_id
            WHERE s.phone = %s
            GROUP BY s.sales_id
            ORDER BY s.sale_date DESC
        ''', (id,))
        
        purchases = cursor.fetchall()
        
        return render_template('customers/view.html', 
                             customer=customer, 
                             purchases=purchases)
        
    except Error as e:
        flash(f'Error retrieving customer: {str(e)}', 'danger')
        return redirect(url_for('list_customers'))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    if request.method == 'POST':
        try:
            name = request.form['name']
            phone = request.form.get('phone', '')
            email = request.form.get('email', '')
            address = request.form.get('address', '')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE customers 
                SET name = %s, phone = %s, email = %s, address = %s
                WHERE customer_id = %s
            ''', (name, phone, email, address, id))
            
            conn.commit()
            flash('Customer updated successfully!', 'success')
            return redirect(url_for('view_customer', id=id))
            
        except Error as e:
            conn.rollback()
            flash(f'Error updating customer: {str(e)}', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    # GET request - show edit form
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM customers WHERE customer_id = %s', (id,))
        customer = cursor.fetchone()
        
        if not customer:
            flash('Customer not found', 'danger')
            return redirect(url_for('list_customers'))
            
        return render_template('customers/edit.html', customer=customer)
        
    except Error as e:
        flash(f'Error retrieving customer: {str(e)}', 'danger')
        return redirect(url_for('list_customers'))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/customers/delete/<int:id>', methods=['POST'])
@login_required
def delete_customer(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if customer has any sales
        cursor.execute('SELECT COUNT(*) as sale_count FROM sales WHERE customer_id = %s', (id,))
        result = cursor.fetchone()
        
        if result['sale_count'] > 0:
            flash('Cannot delete customer with existing sales history', 'danger')
            return redirect(url_for('list_customers'))
        
        cursor.execute('DELETE FROM customers WHERE customer_id = %s', (id,))
        conn.commit()
        
        flash('Customer deleted successfully', 'success')
        
    except Error as e:
        conn.rollback()
        flash('Error deleting customer', 'danger')
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
    
    return redirect(url_for('list_customers'))

# Sales Routes

@app.route('/sales')
@login_required
def list_sales():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute('''
            SELECT s.*, c.name as customer_name, u.username as user_name
            FROM sales s
            LEFT JOIN customers c ON s.phone = c.phone
            LEFT JOIN user u ON s.user_id = u.user_id
            ORDER BY s.sale_date DESC
        ''')
        
        sales = cursor.fetchall()
        return render_template('sales/list.html', sales=sales)
        
    except Error as e:
        flash(f'Error retrieving sales: {str(e)}', 'danger')
        return render_template('sales/list.html', sales=[])
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/sales/new', methods=['GET', 'POST'])
@login_required
def new_sale():
    if request.method == 'POST':
        try:
            customer_phone = request.form.get('customer_phone')
            # Lookup customer_id by phone
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            # No need to look up customer_id; use phone directly
            items = json.loads(request.form['items'])
            
            if not items:
                flash('Please add at least one item to the sale', 'danger')
                return redirect(url_for('new_sale'))
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Calculate total amount
            total_amount = sum(float(item['price']) * int(item['quantity']) for item in items)
            
            # Create sale record
            cursor.execute('''
                INSERT INTO sales (phone, user_id, total_amount)
                VALUES (%s, %s, %s)
            ''', (customer_phone, session['user_id'], total_amount))
            
            sales_id = cursor.lastrowid
            
            # Add sale items
            for item in items:
                cursor.execute('''
                    INSERT INTO sale_items (sales_id, medicine_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                ''', (sales_id, item['medicine_id'], item['quantity'], item['price']))
                
                # Update medicine quantity
                cursor.execute('''
                    UPDATE medicines 
                    SET quantity = quantity - %s 
                    WHERE medicines_id = %s
                ''', (item['quantity'], item['medicine_id']))
            
            conn.commit()
            flash('Sale completed successfully!', 'success')
            return redirect(url_for('view_sale', sales_id=sales_id))
            
        except Error as e:
            conn.rollback()
            flash(f'Error processing sale: {str(e)}', 'danger')
        except json.JSONDecodeError:
            flash('Invalid items data', 'danger')
        except (ValueError, KeyError):
            flash('Invalid input values', 'danger')
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
    
    # For GET request, show the sale form
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get customers for dropdown
        cursor.execute('SELECT customer_id, phone FROM customers ORDER BY phone')
        customers = cursor.fetchall()
        
        # Get medicines for autocomplete
        cursor.execute('SELECT medicines_id, name, price, quantity FROM medicines WHERE quantity > 0 ORDER BY name')
        medicines = cursor.fetchall()
        
        return render_template('sales/new.html', 
                             customers=customers, 
                             medicines=medicines)
        
    except Error as e:
        flash(f'Error loading sale form: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/sales/<int:sales_id>')
@login_required
def view_sale(sales_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get sale details
        cursor.execute('''
            SELECT s.*, c.name as customer_name, c.phone, c.email,
                   u.username as user_name
            FROM sales s
            LEFT JOIN customers c ON s.phone = c.phone
            LEFT JOIN user u ON s.user_id = u.user_id
            WHERE s.sales_id = %s
        ''', (sales_id,))
        
        sale = cursor.fetchone()
        if not sale:
            flash('Sale not found', 'danger')
            return redirect(url_for('list_sales'))
        
        # Get sale items
        cursor.execute('''
            SELECT si.*, m.name as medicine_name, m.manufacturer
            FROM sale_items si
            JOIN medicines m ON si.medicine_id = m.medicines_id
            WHERE si.sales_id = %s
        ''', (sales_id,))
        
        items = cursor.fetchall()
        
        return render_template('sales/view.html', sale=sale, items=items)
        
    except Error as e:
        flash(f'Error retrieving sale details: {str(e)}', 'danger')
        return redirect(url_for('list_sales'))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/sales/print/<int:sales_id>')
@login_required
def print_invoice(sales_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get sale details
        cursor.execute('''
            SELECT s.*, c.name as customer_name, c.phone, c.email, c.address,
                   u.username as user_name
            FROM sales s
            LEFT JOIN customers c ON s.phone = c.phone
            LEFT JOIN user u ON s.user_id = u.user_id
            WHERE s.sales_id = %s
        ''', (sales_id,))
        
        sale = cursor.fetchone()
        if not sale:
            flash('Sale not found', 'danger')
            return redirect(url_for('list_sales'))
        
        # Get sale items
        cursor.execute('''
            SELECT si.*, m.name as medicine_name, m.manufacturer
            FROM sale_items si
            JOIN medicines m ON si.medicine_id = m.medicines_id
            WHERE si.sales_id = %s
        ''', (sales_id,))
        
        items = cursor.fetchall()
        
        return render_template('sales/print.html', 
                             sale=sale, 
                             items=items,
                             datetime=datetime)
        
    except Error as e:
        flash(f'Error generating invoice: {str(e)}', 'danger')
        return redirect(url_for('view_sale', sales_id=sales_id))
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    app.run(debug=True)
