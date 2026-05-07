import streamlit as st
from azure.cosmos import CosmosClient
import os

# --- Page Config ---
st.set_page_config(page_title="Udaipur Travel Guide", page_icon="🏰", layout="wide")
st.title("🏰 Ramona's Guide to Exploring Udaipur")
st.markdown("Discover the best spots in the City of Lakes, updated daily. Built with <3")

# --- Database Connection ---
# Streamlit Cloud uses "st.secrets" instead of os.environ for security
@st.cache_resource
def init_connection():
    # Fallback to os.environ for local testing, use st.secrets on the cloud
    endpoint = st.secrets.get("COSMOS_ENDPOINT", os.getenv("COSMOS_ENDPOINT"))
    key = st.secrets.get("COSMOS_KEY", os.getenv("COSMOS_KEY"))
    
    client = CosmosClient(endpoint, key)
    database = client.get_database_client("udaipur_db")
    return database.get_container_client("spots")

try:
    container = init_connection()
except Exception as e:
    st.error("Failed to connect to the database. Please check your credentials.")
    st.stop()

# --- Fetch Data ---
# We cache this so we don't query Cosmos DB on every single button click
@st.cache_data(ttl=3600) # Cache expires after 1 hour
def fetch_spots():
    query = "SELECT c.title, c.url, c.excerpt, c.category, c.source FROM c"
    items = list(container.query_items(query=query, enable_cross_partition_query=True))
    return items

spots = fetch_spots()

# --- User Interface ---
if not spots:
    st.warning("No spots found in the database yet!")
else:
    # 1. Sidebar Filters
    st.sidebar.header("Filter Options")
    categories = list(set([item.get("category", "general") for item in spots]))
    selected_category = st.sidebar.selectbox("Choose a Category:", ["All"] + categories)

    # 2. Filter the data based on selection
    if selected_category == "All":
        filtered_spots = spots
    else:
        filtered_spots = [item for item in spots if item.get("category") == selected_category]

    st.write(f"Showing **{len(filtered_spots)}** spots.")

    # 3. Display the items in a grid layout
    cols = st.columns(3) # Create 3 columns
    for index, spot in enumerate(filtered_spots):
        col = cols[index % 3]
        with col:
            st.markdown(f"### {spot.get('title')}")
            st.markdown(f"**Category:** {spot.get('category').capitalize()} | **Source:** {spot.get('source')}")
            st.write(spot.get("excerpt", "No description available."))
            st.markdown(f"[Read More]({spot.get('url')})")
            st.divider() # Adds a nice line between items
