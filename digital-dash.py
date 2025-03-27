import streamlit as st
import pandas as pd
import glob
import os
import re
from datetime import datetime, timedelta
import plotly.express as px

# --- Data Loading ---
@st.cache_data(show_spinner=True)
def load_data():
    folders = ["sd", "ws"]
    all_data = []
    for folder in folders:
        csv_files = glob.glob(f"{folder}/*.csv")
        if folder == "sd":
            website_name = "Showdown"
            pattern = r"showdown_(\d{1,2}-\d{1,2}-\d{2})\.csv"
        else:
            website_name = "WS Displays"
            pattern = r"wsdisplay_(\d{1,2}-\d{1,2}-\d{2})\.csv"
        for file in csv_files:
            filename = os.path.basename(file)
            match = re.search(pattern, filename)
            if match:
                date_str = match.group(1)
                try:
                    collection_date = datetime.strptime(date_str, "%m-%d-%y")
                except Exception as e:
                    st.error(f"Date parsing error in file {filename}: {e}")
                    collection_date = None
            else:
                collection_date = None
            try:
                df = pd.read_csv(
                    file,
                    header=None,
                    encoding="cp1252",
                    encoding_errors="replace",
                    on_bad_lines="skip",
                )
            except Exception as e:
                st.error(f"Error reading file {filename}: {e}")
                continue
            df["collection_date"] = collection_date
            df["website"] = website_name
            all_data.append(df)
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    else:
        return pd.DataFrame()

raw_data = load_data()

# --- Data Processing ---
def process_data(df):
    rows = []
    
    # Helper: extract product name (handles HYPERLINK formulas)
    def extract_product(cell):
        cell_str = str(cell)
        match = re.search(r'=HYPERLINK\(".*?",\s*"(.*?)"\)', cell_str)
        product = match.group(1) if match else cell_str.strip()
        product = product.replace("®", "").strip()
        return product
    
    for (website, coll_date), group in df.groupby(["website", "collection_date"]):
        group = group.reset_index(drop=True)
        if website == "Showdown":
            # For Showdown, each product is represented by 3 rows.
            step = 3
            for i in range(0, len(group), step):
                if i + 2 < len(group):
                    product = extract_product(group.iloc[i, 0])
                    if not product or product.strip().lower() == "nan":
                        continue
                    link_url = str(group.iloc[i, 1]).strip() if len(group.columns) > 1 else ""
                    image_url = str(group.iloc[i, 2]).strip() if len(group.columns) > 2 else ""
                    
                    # Slice only the original CSV columns (exclude the last 2 appended columns)
                    raw_qty = group.iloc[i, 3:group.shape[1]-2].tolist()
                    raw_retail = group.iloc[i+1, 3:group.shape[1]-2].tolist()
                    raw_your = group.iloc[i+2, 3:group.shape[1]-2].tolist()
                    
                    qty = [str(x) for x in raw_qty]
                    if qty and qty[0].strip().upper().startswith("QTY"):
                        qty[0] = re.sub(r'(?i)^QTY\s*', '', qty[0])
                    retail_prices = [str(x) for x in raw_retail]
                    your_prices = [str(x) for x in raw_your]
                    numeric_price = None
                    if your_prices:
                        try:
                            numeric_price = float(your_prices[0].replace("$", "").replace(",", "").strip())
                        except:
                            numeric_price = None
                    
                    rows.append({
                        "collection_date": coll_date,
                        "website": website,
                        "product": product,
                        "link_url": link_url,
                        "image_url": image_url,
                        "quantities": qty,
                        "retail_prices": retail_prices,
                        "your_prices": your_prices,
                        "price": numeric_price
                    })
        elif website == "WS Displays":
            # WS Displays processing:
            rows_list = group.values.tolist()
            # Remove the appended collection_date and website columns.
            rows_list = [row[:-2] for row in rows_list]
            i = 0
            while i < len(rows_list):
                current = rows_list[i]
                if current[0] and str(current[0]).strip().lower() != "nan":
                    product = extract_product(current[0])
                    link_url = str(current[1]).strip() if len(current) > 1 else ""
                    image_url = str(current[2]).strip() if len(current) > 2 else ""
                    product_dict = {
                        "collection_date": coll_date,
                        "website": website,
                        "product": product,
                        "link_url": link_url,
                        "image_url": image_url,
                        "options": []
                    }
                    i += 1
                    while i < len(rows_list):
                        row = rows_list[i]
                        if row[0] and str(row[0]).strip().lower() != "nan":
                            break
                        option_text = str(row[3]).strip() if len(row) > 3 else ""
                        if not option_text or option_text.lower() == "nan":
                            i += 1
                            continue
                        raw_qty = row[4:] if len(row) > 4 else []
                        qty = [str(x) for x in raw_qty]
                        price_row = None
                        j = i + 1
                        while j < len(rows_list):
                            candidate = rows_list[j]
                            if (not candidate[0] or str(candidate[0]).strip().lower() == "nan") and any(candidate[k] for k in range(4, len(candidate))):
                                price_row = candidate
                                break
                            j += 1
                        if price_row:
                            raw_prices = price_row[4:] if len(price_row) > 4 else []
                            prices_table = [str(x) for x in raw_prices]
                            product_dict["options"].append({
                                "option": option_text,
                                "quantities": qty,
                                "prices_table": prices_table
                            })
                            i = j + 1
                        else:
                            product_dict["options"].append({
                                "option": option_text,
                                "quantities": qty,
                                "prices_table": []
                            })
                            i += 1
                    numeric_price = None
                    if product_dict["options"] and product_dict["options"][0]["prices_table"]:
                        try:
                            numeric_price = float(product_dict["options"][0]["prices_table"][0].replace("$", "").replace(",", "").strip())
                        except:
                            numeric_price = None
                    product_dict["price"] = numeric_price
                    rows.append(product_dict)
                else:
                    i += 1
        else:
            st.error(f"Unknown website type: {website}")
    return pd.DataFrame(rows)

if not raw_data.empty:
    processed_data = process_data(raw_data)
else:
    processed_data = pd.DataFrame()

# --- Compute Price Movements ---
def compute_price_movements(df):
    summary_rows = []
    grouped = df.groupby(["website", "product"])
    for (website, product), group in grouped:
        group_sorted = group.sort_values(by="collection_date")
        if len(group_sorted) < 2:
            continue
        latest = group_sorted.iloc[-1]
        previous = group_sorted.iloc[-2]
        previous_price = previous["price"]
        latest_price = latest["price"]
        if pd.notnull(previous_price) and pd.notnull(latest_price) and previous_price != latest_price:
            change = latest_price - previous_price
            pct_change = (change / previous_price) * 100 if previous_price != 0 else None
            summary_rows.append({
                "Website": website,
                "Product": product,
                "Previous Date": previous["collection_date"].date(),
                "Previous Price": previous_price,
                "Latest Date": latest["collection_date"].date(),
                "Latest Price": latest_price,
                "Change": change,
                "% Change": pct_change
            })
    return pd.DataFrame(summary_rows)

# --- Sidebar Filters ---
st.sidebar.header("Filters")
if not processed_data.empty:
    processed_data["collection_date"] = pd.to_datetime(processed_data["collection_date"], errors="coerce")
    processed_data.sort_values(by=["website", "product", "collection_date"], inplace=True)
    websites = processed_data["website"].unique().tolist()
    st.sidebar.markdown("### Select Website(s)")
    selected_websites = []
    for website in websites:
        if st.sidebar.checkbox(website, value=False):
            selected_websites.append(website)
    if selected_websites:
        filtered_by_website = processed_data[processed_data["website"].isin(selected_websites)]
    else:
        filtered_by_website = processed_data
else:
    filtered_by_website = processed_data

# --- Main Body: Product Selection & Date Range ---
st.markdown("## Product Search and Selection")
selected_products_global = []
if selected_websites:
    if len(selected_websites) > 1:
        for site in selected_websites:
            site_data = filtered_by_website[filtered_by_website["website"] == site]
            site_products = site_data["product"].unique().tolist()
            selection = st.multiselect(f"Select Product(s) for {site}", site_products, default=[])
            for prod in selection:
                selected_products_global.append((prod, site))
    else:
        site_products = filtered_by_website["product"].unique().tolist()
        selection = st.multiselect("Select Product(s)", site_products, default=[])
        for prod in selection:
            selected_products_global.append((prod, selected_websites[0]))
else:
    selected_products_global = []

if filtered_by_website["collection_date"].notna().any():
    min_date = filtered_by_website["collection_date"].min().date()
    max_date = filtered_by_website["collection_date"].max().date()
    main_date_range = st.date_input("Select Date Range", value=(min_date, max_date), key="main_date_range")
else:
    main_date_range = None

# --- Apply Product and Date Filters ---
if selected_products_global:
    mask = pd.Series([False] * len(filtered_by_website), index=filtered_by_website.index)
    df_sel = pd.DataFrame(selected_products_global, columns=["product", "website"])
    for site, prods in df_sel.groupby("website")["product"]:
        mask |= ((filtered_by_website["website"] == site) & (filtered_by_website["product"].isin(prods)))
    filtered_data = filtered_by_website[mask]
    if main_date_range and isinstance(main_date_range, (list, tuple)) and len(main_date_range) == 2:
        start_date, end_date = main_date_range
        filtered_data = filtered_data[
            (filtered_data["collection_date"].dt.date >= start_date) &
            (filtered_data["collection_date"].dt.date <= end_date)
        ]
else:
    filtered_data = filtered_by_website

# --- Default Homepage View ---
if not selected_products_global:
    st.markdown("## Price Movements by Website")
    summary = compute_price_movements(filtered_by_website)
    if summary.empty:
        st.write("No products have moved in price from the compared period.")
    else:
        summary = summary.drop(columns=["quantities", "retail_prices", "your_prices", "prices_table"], errors="ignore")
        if selected_websites == ["WS Displays"]:
            summary = summary.drop(columns=["Website", "Previous Date", "Latest Date"], errors="ignore")
        st.dataframe(summary)

# --- Global Overlay Chart Across Multiple Websites ---
if len(selected_websites) >= 2 and len(selected_products_global) >= 2:
    st.markdown("## Global Overlay Chart for Selected Products (All Sites)")
    overlay_fig = px.bar(
        filtered_data.assign(day=filtered_data["collection_date"].dt.date),
        x="day",
        y="price",
        color="product",
    )
    overlay_fig.update_layout(
        barmode="group",
        xaxis_title="Collection Date",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
    )
    overlay_fig.update_xaxes(tickformat="%m/%d/%Y")
    st.plotly_chart(overlay_fig, key="global_overlay_chart")

# --- Global Overlay Chart for Selected Products by Site ---
if selected_products_global:
    products_by_site = {}
    for prod, site in selected_products_global:
        products_by_site.setdefault(site, []).append(prod)
    for site, prods in products_by_site.items():
        if len(prods) >= 2:
            st.markdown(f"## Global Overlay Chart for Selected Products on {site}")
            data_site = filtered_data[(filtered_data["website"] == site) & (filtered_data["product"].isin(prods))]
            fig = px.bar(
                data_site.assign(day=data_site["collection_date"].dt.date),
                x="day",
                y="price",
                color="product"
            )
            fig.update_layout(
                barmode="group",
                xaxis_title="Collection Date",
                yaxis_title="Price",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
            )
            fig.update_xaxes(tickformat="%m/%d/%Y")
            st.plotly_chart(fig, key=f"global_overlay_chart_by_site_{site}")

# --- Detailed Chart View ---
def is_date(val):
    try:
        pd.to_datetime(val)
        return True
    except Exception:
        return False

if not processed_data.empty and selected_products_global:
    for prod, site in selected_products_global:
        product_data = filtered_data[(filtered_data["product"] == prod) & (filtered_data["website"] == site)]
        if product_data.empty:
            st.write(f"No data available for {prod} in {site} for the selected date range.")
            continue

        if site.lower() == "ws displays":
            st.markdown(f"### {prod}")
        else:
            st.markdown(f"### {prod} ({site})")
        
        if site.lower() == "showdown":
            if all(col in product_data.columns for col in ["quantities", "retail_prices", "your_prices"]):
                row = product_data.iloc[0]
                qty = row["quantities"]
                retail = row["retail_prices"]
                yours = row["your_prices"]
                if qty and retail and yours:
                    filtered_qty = []
                    filtered_retail = []
                    filtered_yours = []
                    for q, r, y in zip(qty, retail, yours):
                        if q.strip().lower().startswith("nan"):
                            continue
                        if is_date(q) or q.strip().lower() == site.lower():
                            continue
                        if is_date(r) or is_date(y):
                            continue
                        filtered_qty.append(q)
                        filtered_retail.append(r)
                        filtered_yours.append(y)
                    
                    def make_unique(lst):
                        seen = {}
                        result = []
                        for item in lst:
                            if item in seen:
                                seen[item] += 1
                                result.append(f"{item}_{seen[item]}")
                            else:
                                seen[item] = 0
                                result.append(item)
                        return result
                    
                    unique_qty = make_unique(filtered_qty)
                    
                    cols = st.columns([1, 2])
                    with cols[0]:
                        link_url = row.get("link_url", "")
                        image_url = row.get("image_url", "")
                        if image_url and image_url.lower() != "nan":
                            if link_url:
                                st.markdown(f'<a href="{link_url}" target="_blank"><img src="{image_url}" width="300"></a>', unsafe_allow_html=True)
                            else:
                                st.image(image_url, width=300)
                    with cols[1]:
                        table_df = pd.DataFrame(
                            [filtered_retail, filtered_yours],
                            index=["Retail Price", "Your Price"],
                            columns=unique_qty
                        )
                        st.table(table_df)
                    
                    st.plotly_chart(
                        px.line(
                            product_data.assign(day=product_data["collection_date"].dt.date),
                            x="day",
                            y="price",
                            markers=True
                        ).update_layout(
                            xaxis_title="Collection Date",
                            yaxis_title="Price",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
                        ).update_xaxes(tickformat="%m/%d/%Y"),
                        key=f"showdown_chart_{prod}_{site}"
                    )
                else:
                    st.write("Pricing table data is missing.")
            else:
                st.write("Pricing table data is not available for this product.")
        
        elif site.lower() == "ws displays":
            if "options" in product_data.columns:
                row = product_data.iloc[0]
                link_url = row.get("link_url", "")
                image_url = row.get("image_url", "")
                
                if image_url and image_url.lower() != "nan":
                    st.markdown(
                        f'<a href="{link_url}" target="_blank"><img src="{image_url}" width="300"></a>',
                        unsafe_allow_html=True
                    )
                
                options = row.get("options", [])
                for opt in options:
                    st.markdown(f"**Product Option:** {opt.get('option', '')}")
                    qty = opt.get("quantities", [])
                    prices_table = opt.get("prices_table", [])
                    
                    clean_qty = [
                        q.strip() for q in qty 
                        if not re.match(r'^\d{4}-\d{2}-\d{2}', q.strip()) 
                        and q.strip().lower() != site.lower()
                    ]
                    clean_prices = [
                        p.strip() for p in prices_table 
                        if not re.match(r'^\d{4}-\d{2}-\d{2}', p.strip()) 
                        and p.strip().lower() != site.lower()
                    ]
                    
                    # Instead of truncating clean_prices to match clean_qty,
                    # pad clean_qty with default headers if there are more prices.
                    if len(clean_prices) > len(clean_qty):
                        extra_headers = [f"Option {i+1}" for i in range(len(clean_qty), len(clean_prices))]
                        clean_qty.extend(extra_headers)
                    elif len(clean_prices) < len(clean_qty):
                        clean_qty = clean_qty[:len(clean_prices)]
                    
                    if clean_prices:
                        if len(clean_prices) == 1:
                            # Single price: create a simple two-column table.
                            df_ws = pd.DataFrame([["Price", clean_prices[0]]], columns=["Label", "Value"])
                            st.table(df_ws)
                        else:
                            def make_unique(lst):
                                seen = {}
                                result = []
                                for item in lst:
                                    if item in seen:
                                        seen[item] += 1
                                        result.append(f"{item}_{seen[item]}")
                                    else:
                                        seen[item] = 0
                                        result.append(item)
                                return result
                            
                            unique_qty = make_unique(clean_qty)
                            df_ws = pd.DataFrame([clean_prices], index=["Price"], columns=unique_qty)
                            html_table = df_ws.to_html(index=False, escape=False)
                            html_table = re.sub(r'>(nan(?:_\d+)?)<', '><', html_table)
                            st.markdown(html_table, unsafe_allow_html=True)
                    else:
                        st.write("Pricing table data is missing for this option.")
                
                st.plotly_chart(
                    px.line(
                        product_data.assign(day=product_data["collection_date"].dt.date),
                        x="day",
                        y="price",
                        markers=True
                    ).update_layout(
                        xaxis_title="Collection Date",
                        yaxis_title="Price",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
                    ).update_xaxes(tickformat="%m/%d/%Y"),
                    key=f"ws_display_chart_{prod}_{site}"
                )
            else:
                st.write("Pricing table data is not available for this product.")

        else:
            st.plotly_chart(
                px.line(
                    product_data.assign(day=product_data["collection_date"].dt.date),
                    x="day",
                    y="price",
                    markers=True
                ).update_layout(
                    xaxis_title="Collection Date",
                    yaxis_title="Price",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
                ).update_xaxes(tickformat="%m/%d/%Y"),
                key=f"chart_{prod}_{site}"
            )
			
st.markdown("## Download Raw Data Per Day")
if not raw_data.empty:
    raw_data["collection_date"] = pd.to_datetime(raw_data["collection_date"], errors="coerce")
    websites_raw = raw_data["website"].unique().tolist()
    selected_website_raw = st.selectbox("Select Website for Raw Data", websites_raw, key="raw_website")
    raw_data_filtered = raw_data[raw_data["website"] == selected_website_raw]
    if not raw_data_filtered.empty:
        min_date = raw_data_filtered["collection_date"].min().date()
        max_date = raw_data_filtered["collection_date"].max().date()
        selected_date_raw = st.date_input("Select Date for Raw Data", value=max_date, min_value=min_date, max_value=max_date, key="raw_date")
        raw_data_day = raw_data_filtered[raw_data_filtered["collection_date"].dt.date == selected_date_raw]
        if raw_data_day.empty:
            st.write("No raw data available for this day.")
        else:
            csv_data_raw = raw_data_day.drop(columns=["collection_date", "website"], errors="ignore").to_csv(index=False).encode("utf-8")
            st.download_button("Download Raw Data", csv_data_raw, f"raw_data_{selected_website_raw}_{selected_date_raw}.csv", "text/csv")
    else:
        st.write("No raw data available for the selected website.")
else:
    st.write("No raw data available!")
