
from typing import List
import faust
import numpy as np
import math
from datetime import datetime
from parking_violations import ParkingViolation
from stream_stats import StreamStats, StreamDateStats, CounterDateStats
from collections import Counter, deque
from river.cluster import DenStream
import matplotlib.pyplot as plt
import time

# Initialize lists to store data points and their cluster IDs
buffer_size = 100000
data_points = deque(maxlen=buffer_size)
cluster_ids = deque(maxlen=buffer_size)

topic = "parking_violations"

app = faust.App(topic, broker='kafka://localhost:29092')
print(f"App is {app}")

violations_topic = app.topic(topic, value_type=ParkingViolation)

@app.agent(violations_topic)
async def process_violations(violations: List[ParkingViolation]):
    # Initialize the DenStream
    denstream = DenStream(epsilon=0.01, mu=30, beta=0.2)

    all_data_stats = StreamDateStats()
    borough_stats = CounterDateStats()
    streets_stats = CounterDateStats()

    tmp_all_data_stats = StreamDateStats()
    tmp_borough_stats = CounterDateStats()
    tmp_streets_stats = CounterDateStats()

    current_year = None
    current_month = None
    current_day = None

    code_to_borough = {
        1: "Manhattan",
        2: "Bronx",
        3: "Brooklyn",
        4: "Queens",
        5: "Staten Island"
    }

    async for violation in violations:
        violation.issue_date = datetime.strptime(violation.issue_date, '%Y-%m-%d %H:%M:%S')

        if current_year is None:
            current_year = violation.issue_date.year
            current_month = violation.issue_date.month
            current_day = violation.issue_date.day

        # If a new day starts, reset the day
        if violation.issue_date.day != current_day:
            tmp_all_data_stats.reset_day()
            tmp_borough_stats.reset_day()
            tmp_streets_stats.reset_day()

            all_data_stats.reset_day()
            borough_stats.reset_day()
            streets_stats.reset_day()

            current_day = violation.issue_date.day

        # If a new month starts, print the daily stats of the previous month (mean of violations per day) and clear the stats
        if violation.issue_date.month != current_month:
            tmp_all_data_stats.reset_month()
            tmp_borough_stats.reset_month()
            tmp_streets_stats.reset_month()

            all_data_stats.reset_month()
            borough_stats.reset_month()
            streets_stats.reset_month()

            print(f"Daily stats of month {current_month} of year {current_year}:")
            print(f"- Overall stats: total: {tmp_all_data_stats.total_count}, {tmp_all_data_stats.day}")
            print("- Borough stats:")
            for borough, stats in tmp_borough_stats.items():
                borough_name = code_to_borough[int(float(borough))]
                print(f".      {borough_name} stats: total: {stats.total_count}, {stats.day}")
            print("- Most common streets:")
            for idx, street in enumerate(tmp_streets_stats.most_commons(10)):
                print(f".      Street {idx + 1} ({street[0]}) stats: total: {street[1].total_count}, {street[1].day}")
            print()

            # clear the rolling stats
            tmp_all_data_stats.clear_day()
            tmp_borough_stats.clear_day()
            tmp_streets_stats.clear_day()

            current_month = violation.issue_date.month

        # if a new year starts, print the stats of the previous year (mean of violations per month) and clear the stats
        if violation.issue_date.year != current_year:
            tmp_all_data_stats.reset_year()
            tmp_borough_stats.reset_year()
            tmp_streets_stats.reset_year()

            all_data_stats.reset_year()
            borough_stats.reset_year()
            streets_stats.reset_year()

            print(f"Monthly stats of year {current_year}:")
            print(f"- Overall stats: total: {tmp_all_data_stats.total_count}, {tmp_all_data_stats.month}")
            print("- Borough stats:")
            for borough, stats in tmp_borough_stats.items():
                borough_name = code_to_borough[int(float(borough))]
                print(f".      {borough_name} stats: total: {stats.total_count}, {stats.month}")
            print("- Most common streets:")
            for idx, street in enumerate(tmp_streets_stats.most_commons(10)):
                print(f".      Street {idx + 1} ({street[0]}) stats: total: {street[1].total_count}, {street[1].month}")
            print()

            # clear the rolling stats
            tmp_all_data_stats.clear_month()
            tmp_borough_stats.clear_month()
            tmp_streets_stats.clear_month()

            current_year = violation.issue_date.year

        # print the overall stats of the data every 2000000 records
        if all_data_stats.total_count % 2000000 == 0 and all_data_stats.total_count != 0:
            # print overall data stats
            print(f"Overall stats from beginning:")
            print("- Overall stats: total: {all_data_stats.total_count}")
            print(f".      yearly: {all_data_stats.year}")
            print(f".      monthly: {all_data_stats.month}")
            print(f".      daily: {all_data_stats.day}")
            print("- Borough stats:")
            for borough, stats in tmp_borough_stats.items():
                print(f".      {borough} stats: {stats.total_count}")
                print(f".             yearly: {stats.year}")
                print(f".             monthly: {stats.month}")
                print(f".             daily: {stats.day}")
            print("- Most common streets:")
            for idx, street in enumerate(tmp_streets_stats.most_commons(10)):
                print(f".      Street {idx + 1} ({street[0]}) stats: total: {street[1].total_count}")
                print(f".             yearly: {street[1].year}")
                print(f".             monthly: {street[1].month}")
                print(f".             daily: {street[1].day}")
            print()

        # increase the stats with current violation
        all_data_stats.increase()
        borough_stats.increase(violation.violation_county)
        streets_stats.increase(violation.street_code)

        tmp_all_data_stats.increase()
        tmp_borough_stats.increase(violation.violation_county)
        tmp_streets_stats.increase(violation.street_code)

        # update the denstream with the current violation
        denstream.learn_one({"latitude": float(violation.latitude), "longitude": float(violation.longitude)})

        # Store the data point and its cluster ID
        data_points.append((float(violation.latitude), float(violation.longitude)))
        cluster_ids.append(denstream.predict_one({"latitude": float(violation.latitude), "longitude": float(violation.longitude)}))

        if all_data_stats.total_count % 200000 == 0 and all_data_stats.total_count != 0:
            print(f"Denstream stats: {denstream.n_clusters}")

            if denstream.n_clusters > 1:
                # Plot the clusters
                plt.figure(figsize=(10, 6))
                plt.scatter(
                    [point[1] for point in data_points],
                    [point[0] for point in data_points],
                    c=cluster_ids,
                    cmap='viridis',
                    marker='o',
                    alpha=0.1,
                    s=10
                )
                plt.title('DenStream Clusters')
                plt.xlabel('Longitude')
                plt.ylabel('Latitude')
                plt.colorbar(label='Cluster ID')

                # Save the plot as a PDF file
                plt.savefig(f'plots/denstream_clusters_{all_data_stats.total_count}.pdf', format='pdf')
                plt.close()
