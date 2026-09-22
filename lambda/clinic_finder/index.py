```python
"""
MedBridge — Clinic Finder Lambda
Copy this to: medbridge/lambda/clinic_finder/index.py

Finds nearest health facilities (PHC/CHC/Hospital) based on user's location.
Uses Haversine distance calculation for sorting by proximity.
"""

import json
import os
import math
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["FACILITIES_TABLE"])


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in kilometers."""
    R = 6371  # Earth's radius in km

    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def decimal_to_float(obj):
    """Convert DynamoDB Decimal types to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_float(i) for i in obj]
    return obj


def handler(event, context):
    try:
        params = event.get("queryStringParameters", {}) or {}

        lat = params.get("lat")
        lng = params.get("lng")
        state = params.get("state", "Tamil Nadu")
        district = params.get("district", "")
        facility_type = params.get("type", "")  # phc, chc, hospital, all
        radius_km = float(params.get("radius", 50))  # default 50km
        limit = int(params.get("limit", 10))

        if not lat or not lng:
            return response(400, {
                "error": "Location required. Please provide lat and lng parameters."
            })

        user_lat = float(lat)
        user_lng = float(lng)

        # Query facilities by state (and optionally district)
        if district:
            result = table.query(
                IndexName="state-district-index",
                KeyConditionExpression=Key("state").eq(state) & Key("district").eq(district),
            )
        else:
            result = table.query(
                IndexName="state-district-index",
                KeyConditionExpression=Key("state").eq(state),
            )

        facilities = result.get("Items", [])

        # Filter by facility type if specified
        if facility_type and facility_type != "all":
            facilities = [f for f in facilities if f.get("type", "").lower() == facility_type.lower()]

        # Calculate distances and sort
        for facility in facilities:
            f_lat = float(facility.get("latitude", 0))
            f_lng = float(facility.get("longitude", 0))
            facility["distance_km"] = round(haversine_distance(user_lat, user_lng, f_lat, f_lng), 2)

        # Filter by radius
        facilities = [f for f in facilities if f["distance_km"] <= radius_km]

        # Sort by distance (nearest first)
        facilities.sort(key=lambda f: f["distance_km"])

        # Limit results
        facilities = facilities[:limit]

        # Clean up Decimal types
        facilities = decimal_to_float(facilities)

        return response(200, {
            "success": True,
            "count": len(facilities),
            "user_location": {"lat": user_lat, "lng": user_lng},
            "radius_km": radius_km,
            "facilities": facilities,
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return response(500, {"error": "Failed to find clinics. Please try again."})


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
```