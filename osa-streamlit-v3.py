import streamlit as st
import pandas as pd
import os
import h3
from odp.client import OdpClient

# Set page configuration
st.set_page_config(
    page_title="Ocean Sensitive Areas Query Tool",
    page_icon="🌊",
    layout="wide"
)

# Title and description
st.title("Ocean Sensitive Areas Query Tool")
st.markdown("""
This application helps you query the HUB Ocean Ocean Sensitive Area Data Product 
to return results based on your own asset data.
""")

# Initialize session state variables if they don't exist
if 'processed_df' not in st.session_state:
    st.session_state.processed_df = None
if 'final_results_df' not in st.session_state:
    st.session_state.final_results_df = None
if 'distance_km' not in st.session_state:
    st.session_state.distance_km = 50
if 'asset_reports' not in st.session_state:
    st.session_state.asset_reports = {}

# Biodiversity analysis functions
def categorize_shannon(shannon):
    if shannon is None:
        return "N/A"
    if shannon < 2.0:
        return "Low Biodiversity"
    elif 2.0 <= shannon <= 4.0:
        return "Medium Biodiversity"
    else:
        return "High Biodiversity"

def categorize_simpson(simpson):
    if simpson is None:
        return "N/A"
    if simpson > 0.5:
        return "High Dominance, Low Evenness"
    elif 0.2 <= simpson <= 0.5:
        return "Moderate Dominance"
    else:
        return "Low Dominance, High Evenness"

def generate_asset_report(df, radius_km):
    report_dict = {}
    
    # Compute asset ranking based on average Shannon Index
    asset_ranks = df.groupby("asset_id")["shannon"].mean().rank(ascending=False).to_dict()
    
    # Sort assets by biodiversity rank (higher Shannon Index first)
    sorted_assets = df.groupby("asset_id")["shannon"].mean().sort_values(ascending=False).index
    
    for asset_id in sorted_assets:
        asset_df = df[df['asset_id'] == asset_id]
        
        # Extract exact location row
        exact_location = asset_df[asset_df['is_neighbor'].str.lower() == "asset"]
        if not exact_location.empty:
            exact_shannon = exact_location['shannon'].values[0]
            exact_simpson = exact_location['simpson'].values[0]
            ecosystems = [eco.capitalize() for eco in ['mangrove', 'seamount', 'cold_water_coral', 'seagrass', 'coral'] 
                          if eco in exact_location.columns and exact_location[eco].values[0] > 0]
            
            # Extract name if it exists
            asset_name = exact_location['name'].values[0] if 'name' in exact_location.columns else None
        else:
            exact_shannon, exact_simpson, ecosystems, asset_name = None, None, [], None
            
        # Extract surrounding data
        neighbors = asset_df[asset_df['is_neighbor'].str.lower() == "neighbor"]
        avg_shannon = neighbors['shannon'].mean() if not neighbors.empty else None
        avg_simpson = neighbors['simpson'].mean() if not neighbors.empty else None
        
        # Rank and total assets
        asset_rank = asset_ranks.get(asset_id, None)
        total_assets = df['asset_id'].nunique()
        
        # Helper function to format with default value
        def safe_format(value):
            return f"{value:.3f}" if value is not None else "N/A"
        
        # Construct Report
        report = f"""
Asset ID: {asset_id}"""

        # Add name if it exists
        if asset_name is not None:
            report += f"\nName: {asset_name}"
            
        report += f"""
Biodiversity Rank: #{int(asset_rank) if asset_rank else "N/A"} out of {total_assets}
-----------------------------------
Exact Location:
  - Shannon Index: {safe_format(exact_shannon)} ({categorize_shannon(exact_shannon)})
  - Simpson Index: {safe_format(exact_simpson)} ({categorize_simpson(exact_simpson)})
  - Ecosystems: {', '.join(ecosystems) if ecosystems else "None"}
Surrounding Area ({radius_km}km radius):
  - Avg Shannon Index: {safe_format(avg_shannon)} ({categorize_shannon(avg_shannon)})
  - Avg Simpson Index: {safe_format(avg_simpson)} ({categorize_simpson(avg_simpson)})
"""
        # Add ecosystem coverage if available
        if not neighbors.empty:
            report += "  - % Coverage:\n"
            for eco in ['coral', 'seagrass', 'cold_water_coral', 'mangrove', 'seamount']:
                if eco in neighbors.columns:
                    report += f"    - {eco.replace('_', ' ').title()}: {safe_format(neighbors[eco].mean() * 100)}%\n"
        
        report_dict[asset_id] = {
            "report": report, 
            "rank": asset_rank,
            "name": asset_name  # Store the name for use in display
        }
    
    return report_dict

# Function to load and process asset data
def load_and_process_asset_data(uploaded_file, distance_km=50):
    """
    Loads asset data from an uploaded file, verifies required columns (case insensitive),
    and adds an H3 index (resolution 6) column based on latitude and longitude.
    Also computes surrounding H3 indexes within a specified distance.
    """
    try:
        # Determine file type and read the data with encoding handling
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file, encoding="utf-8")
        elif uploaded_file.name.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            st.error("Unsupported file format. Use CSV or Excel (.xls/.xlsx).")
            return None
    except UnicodeDecodeError:
        df = pd.read_csv(uploaded_file, encoding="ISO-8859-1")
        
    # Normalize column names (convert to lowercase for easy matching)
    df.columns = df.columns.str.lower()
    
    # Define possible column name variations
    lat_columns = {'latitude', 'lat'}
    lon_columns = {'longitude', 'long', 'lon'}
    asset_id_columns = {'asset_id', 'id', 'assetid'}
    name_columns = {'name', 'asset_name', 'title', 'label'}
    
    # Find actual column names in the dataset
    lat_col = next((col for col in df.columns if col in lat_columns), None)
    lon_col = next((col for col in df.columns if col in lon_columns), None)
    asset_id_col = next((col for col in df.columns if col in asset_id_columns), None)
    name_col = next((col for col in df.columns if col in name_columns), None)
    
    # Validate presence of required columns
    if not lat_col or not lon_col:
        st.error("Error: The file must contain 'latitude' and 'longitude' (or 'lat' and 'long') columns.")
        return None
    
    if not asset_id_col:
        st.warning("No asset ID column found. Adding a sequential ID column.")
        df['asset_id'] = range(1, len(df) + 1)
        asset_id_col = 'asset_id'
    
    # Compute H3 index at resolution 6
    df['h3_index'] = df.apply(lambda row: h3.latlng_to_cell(row[lat_col], row[lon_col], 6), axis=1)
    
    # Compute surrounding H3 hexagons within the given distance
    def get_h3_neighbors(h3_index):
        num_rings = round(distance_km / 8.74)  # Approximate conversion for resolution 6
        return list(h3.grid_disk(h3_index, num_rings))
    
    df['h3_neighbors'] = df['h3_index'].apply(get_h3_neighbors)
    
    # Create a standardized DataFrame with consistent column names
    result_columns = {
        'asset_id': df[asset_id_col],
        'lat': df[lat_col],
        'lon': df[lon_col],
        'h3_index': df['h3_index'],
        'h3_neighbors': df['h3_neighbors']
    }
    
    # Add name column if it exists
    if name_col:
        result_columns['name'] = df[name_col]
    
    result_df = pd.DataFrame(result_columns)
    
    return result_df

# Function to query Ocean Sensitive Areas Dataset
def query_osa_data(df):
    with st.spinner("Connecting to HUB Ocean Ocean Sensitive Area Data..."):
        # Connect to ODP client
        client = OdpClient()
        
        # Request the dataset from the catalog using the UUID
        osa_table_dataset = client.catalog.get(("468bef0c-5934-44e6-bd3e-5a60a0b326b6"))
        osa_data = client.table_v2(osa_table_dataset)
        
        st.success(f"Connected to dataset: {osa_table_dataset.metadata.display_name}")
    
    # Initialize an empty list to store the results for all assets
    all_results = []
    
    progress_bar = st.progress(0)
    total_assets = len(df)
    
    # Loop through each asset in the DataFrame
    for i, (_, row) in enumerate(df.iterrows()):
        # Update progress
        progress_bar.progress((i + 1) / total_assets)
        
        # Get the asset's H3 index and neighbors
        hex6_set = {row['h3_index']}  # Add the asset's H3 index
        hex6_set.update(row['h3_neighbors'])  # Add its neighbors
        
        # Convert the set to a list for query construction
        hex6_array = list(hex6_set)
        
        # Build the query using OR conditions
        query = " OR ".join(f'hex6 == "{h}"' for h in hex6_array)
        
        try:
            # Execute the query to get results for the current asset and its neighbors
            result_df = next(osa_data.select(query).dataframes())
            
            # Add a column to indicate whether the record is a neighbor or the main asset
            result_df['is_neighbor'] = result_df['hex6'].apply(
                lambda x: 'Neighbor' if x != row['h3_index'] and x in row['h3_neighbors'] else 'Asset'
            )
            
            # Add the asset_id to the results
            result_df['asset_id'] = row['asset_id']
            
            # Add asset name if it exists
            if 'name' in row:
                result_df['name'] = row['name']
            
            # Append the result to the all_results list
            all_results.append(result_df)
        except Exception as e:
            st.warning(f"Error querying for asset {row['asset_id']}: {e}")
    
    # Concatenate all the individual results into a single DataFrame
    if all_results:
        final_results_df = pd.concat(all_results, ignore_index=True)
        return final_results_df
    else:
        st.error("No results found for any assets.")
        return None

# Create sidebar for file upload and parameters
with st.sidebar:
    st.header("Parameters")
    
    # File uploader
    uploaded_file = st.file_uploader(
        "Upload your asset data (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        help="File should contain columns for asset_id, latitude/lat, longitude/long/lon, and optionally name"
    )
    
    # Distance slider
    distance_km = st.slider(
        "Distance (km) for neighboring hexagons",
        min_value=10,
        max_value=200,
        value=50,
        step=5,
        help="Radius in kilometers around each asset to include in the query"
    )
    
    # Store distance_km in session state for analysis tab
    st.session_state.distance_km = distance_km
    
    # Process button
    process_button = st.button("Process Asset Data")
    
    if process_button and uploaded_file is not None:
        with st.spinner("Processing asset data..."):
            processed_df = load_and_process_asset_data(uploaded_file, distance_km)
            if processed_df is not None:
                st.session_state.processed_df = processed_df
                st.success(f"Processed {len(processed_df)} assets successfully")
    
    # Query button (only enabled if data is processed)
    query_button = st.button(
        "Query Ocean Sensitive Areas",
        disabled=st.session_state.processed_df is None
    )
    
    if query_button and st.session_state.processed_df is not None:
        with st.spinner("Querying Ocean Sensitive Areas..."):
            final_results_df = query_osa_data(st.session_state.processed_df)
            if final_results_df is not None:
                st.session_state.final_results_df = final_results_df
                st.success(f"Found {len(final_results_df)} records")

# Main content - added Analysis tab
tabs = st.tabs(["Asset Data", "Query Results", "Analysis"])

# Asset Data Tab
with tabs[0]:
    if st.session_state.processed_df is not None:
        st.subheader("Processed Asset Data")
        st.dataframe(st.session_state.processed_df.drop(columns=['h3_neighbors']))
        
        # Display some sample H3 neighbors
        if len(st.session_state.processed_df) > 0:
            st.subheader("Sample H3 Neighbors")
            sample_asset = st.session_state.processed_df.iloc[0]
            st.write(f"Asset ID: {sample_asset['asset_id']}")
            if 'name' in sample_asset:
                st.write(f"Name: {sample_asset['name']}")
            st.write(f"H3 Index: {sample_asset['h3_index']}")
            st.write(f"Number of neighboring hexagons: {len(sample_asset['h3_neighbors'])}")
            st.write("Sample neighbors (first 5):")
            st.write(", ".join(sample_asset['h3_neighbors'][:5]))
    else:
        st.info("Upload your asset data file and click 'Process Asset Data' to get started.")

# Query Results Tab
with tabs[1]:
    if st.session_state.final_results_df is not None:
        st.subheader("Query Results")
        st.dataframe(st.session_state.final_results_df)
        
        # Download button for results
        csv = st.session_state.final_results_df.to_csv(index=False)
        st.download_button(
            label="Download Results as CSV",
            data=csv,
            file_name="osa_results.csv",
            mime="text/csv"
        )
        
        # Show basic summary statistics
        st.subheader("Summary Statistics")
        
        # Asset counts
        st.write(f"Total number of assets: {st.session_state.processed_df['asset_id'].nunique()}")
        st.write(f"Total records in results: {len(st.session_state.final_results_df)}")
    else:
        st.info("Process your asset data and query the Ocean Sensitive Areas dataset to see results here.")

# Analysis Tab (New)
with tabs[2]:
    if st.session_state.final_results_df is not None:
        st.subheader("Biodiversity Analysis")
        
        # Generate biodiversity reports
        with st.spinner("Generating biodiversity reports..."):
            df = st.session_state.final_results_df
            
            # Check if required columns exist
            required_cols = ['shannon', 'simpson']
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                st.error(f"Missing required columns in dataset: {', '.join(missing_cols)}")
                st.info("The analysis requires Shannon and Simpson indices to be present in the dataset.")
            else:
                # Generate reports and store in session state
                st.session_state.asset_reports = generate_asset_report(df, st.session_state.distance_km)
                
                # Create two display options
                display_option = st.radio(
                    "Display Options", 
                    ["Ranked by Biodiversity", "Select by Asset ID"],
                    horizontal=True
                )
                
                if display_option == "Ranked by Biodiversity":
                    # Sort by rank (lower rank number = higher biodiversity)
                    sorted_assets = sorted(
                        st.session_state.asset_reports.items(),
                        key=lambda x: (x[1]["rank"] if x[1]["rank"] is not None else float('inf'))
                    )
                    
                    # Create selection options with rank and name (if available)
                    options = []
                    for asset_id, info in sorted_assets:
                        option_text = f"#{int(info['rank'])} - Asset ID: {asset_id}"
                        if info['name'] is not None:
                            option_text += f" ({info['name']})"
                        options.append(option_text)
                    
                    # Display the dropdown with ranking information
                    if options:
                        selected_option = st.selectbox(
                            "Select Asset by Biodiversity Rank", 
                            options=options
                        )
                        
                        # Extract asset_id from the selected option
                        selected_asset_id = int(selected_option.split("Asset ID: ")[1].split(" ")[0])
                        
                        # Display the report
                        st.text_area(
                            "Biodiversity Report", 
                            st.session_state.asset_reports[selected_asset_id]["report"], 
                            height=400
                        )
                
                else:  # "Select by Asset ID"
                    # Get all asset IDs and sort them numerically
                    asset_ids = sorted(st.session_state.asset_reports.keys())
                    
                    if asset_ids:
                        # Create a format function to include name if available
                        def format_asset_option(asset_id):
                            asset_info = st.session_state.asset_reports[asset_id]
                            if asset_info['name'] is not None:
                                return f"Asset ID: {asset_id} ({asset_info['name']})"
                            else:
                                return f"Asset ID: {asset_id}"
                        
                        selected_asset = st.selectbox(
                            "Select Asset to View Report", 
                            options=asset_ids,
                            format_func=format_asset_option
                        )
                        
                        # Display the report for the selected asset
                        st.text_area(
                            "Biodiversity Report", 
                            st.session_state.asset_reports[selected_asset]["report"], 
                            height=400
                        )
                
                # Option to download all reports
                all_reports = "\n\n" + "-"*80 + "\n\n".join(
                    [info["report"] for info in st.session_state.asset_reports.values()]
                )
                st.download_button(
                    label="Download All Reports as TXT",
                    data=all_reports,
                    file_name="biodiversity_reports.txt",
                    mime="text/plain"
                )
    else:
        st.info("Process your asset data and query the Ocean Sensitive Areas dataset to generate biodiversity analysis.")