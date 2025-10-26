# views.py - Enhanced Peza API

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import logging
from math import radians, sin, cos, sqrt, atan2

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET"])
def peza_api(request):
    """
    Enhanced API to find nearby emergency services
    GET /api/peza/?lat=-13.9626&lon=33.7741&category=hospital
    """
    try:
        # Get parameters with validation
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        category = request.GET.get('category', 'all')
        radius = int(request.GET.get('radius', 5000))  # Default 5km
        
        # Validate coordinates
        if not lat or not lon:
            return JsonResponse({
                "error": "Missing required parameters: lat and lon"
            }, status=400)
        
        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            return JsonResponse({
                "error": "Invalid coordinates format"
            }, status=400)
        
        # Validate radius (max 20km for performance)
        if radius > 20000:
            radius = 20000
        
        # Map service categories to Overpass API tags
        category_map = {
            'police': 'amenity=police',
            'hospital': 'amenity=hospital',
            'ambulance': 'amenity~"hospital|clinic|doctors"',
            'fire': 'amenity=fire_station',
            'pharmacy': 'amenity=pharmacy',
            'utility': 'office~"company|government"'
        }
        
        # Build Overpass query
        if category == 'all':
            query_filter = 'amenity~"police|hospital|fire_station|clinic"'
        else:
            query_filter = category_map.get(category, 'amenity=hospital')
        
        overpass_query = f"""
            [out:json][timeout:15];
            (
                node[{query_filter}](around:{radius},{lat},{lon});
                way[{query_filter}](around:{radius},{lat},{lon});
                relation[{query_filter}](around:{radius},{lat},{lon});
            );
            out center tags;
        """
        
        # Call Overpass API
        url = "https://overpass-api.de/api/interpreter"
        logger.debug(f"Querying Overpass API for {category} near ({lat}, {lon})")
        
        response = requests.post(
            url,
            data={'data': overpass_query},
            timeout=20,
            headers={'User-Agent': 'Peza Safety App/1.0'}
        )
        response.raise_for_status()
        data = response.json()
        
        # Parse and enrich results
        locations = []
        seen_coords = set()  # Avoid duplicates
        
        for element in data.get("elements", []):
            # Get coordinates (handle nodes vs ways/relations)
            elem_lat = element.get('lat') or element.get('center', {}).get('lat')
            elem_lon = element.get('lon') or element.get('center', {}).get('lon')
            
            if not elem_lat or not elem_lon:
                continue
            
            # Avoid duplicates (same location)
            coord_key = f"{elem_lat:.5f},{elem_lon:.5f}"
            if coord_key in seen_coords:
                continue
            seen_coords.add(coord_key)
            
            # Extract tags
            tags = element.get("tags", {})
            name = tags.get("name", "Unknown Location")
            
            # Skip unnamed locations unless it's a critical service
            if name == "Unknown Location" and category not in ['police', 'hospital', 'fire']:
                continue
            
            # Calculate distance
            distance_text, distance_meters = calculate_distance(lat, lon, float(elem_lat), float(elem_lon))
            
            # Build location object
            location = {
                "name": name,
                "category": tags.get("amenity", category),
                "address": format_address(tags),
                "distance": distance_text,
                "distance_meters": distance_meters,
                "lat": elem_lat,
                "lon": elem_lon,
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "opening_hours": tags.get("opening_hours", ""),
                "website": tags.get("website", tags.get("contact:website", "")),
                "emergency": tags.get("emergency", "") == "yes",
                "operator": tags.get("operator", ""),
            }
            
            locations.append(location)
        
        # Sort by distance
        locations.sort(key=lambda x: x['distance_meters'])
        
        # Limit results to top 20
        locations = locations[:20]
        
        logger.info(f"Found {len(locations)} {category} services near ({lat}, {lon})")
        
        return JsonResponse({
            "success": True,
            "count": len(locations),
            "locations": locations,
            "search_params": {
                "latitude": lat,
                "longitude": lon,
                "category": category,
                "radius_meters": radius
            }
        }, safe=False)
        
    except requests.RequestException as e:
        logger.error(f"Overpass API error: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": "Failed to fetch emergency services. Please try again.",
            "details": str(e)
        }, status=503)
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return JsonResponse({
            "success": False,
            "error": "Internal server error",
            "details": str(e)
        }, status=500)


def format_address(tags):
    """Format address from OSM tags"""
    parts = []
    
    # Street address
    street = tags.get("addr:street", "")
    housenumber = tags.get("addr:housenumber", "")
    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif street:
        parts.append(street)
    
    # City/suburb
    city = tags.get("addr:city", tags.get("addr:suburb", ""))
    if city:
        parts.append(city)
    
    # If no address found, try other fields
    if not parts:
        if tags.get("addr:place"):
            parts.append(tags.get("addr:place"))
        elif tags.get("location"):
            parts.append(tags.get("location"))
    
    return ", ".join(parts) if parts else "Address not available"


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two points using Haversine formula
    Returns tuple: (formatted_string, distance_in_meters)
    """
    R = 6371  # Earth's radius in km
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance_km = R * c
    distance_meters = int(distance_km * 1000)
    
    # Format string appropriately
    if distance_km < 1:
        distance_text = f"{distance_meters} m"
    else:
        distance_text = f"{distance_km:.1f} km"
    
    return distance_text, distance_meters


@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """Simple health check endpoint"""
    return JsonResponse({
        "status": "ok",
        "service": "Peza Emergency Services API",
        "version": "1.0.0"
    })


@csrf_exempt  
@require_http_methods(["POST"])
def emergency_alert(request):
    """
    Handle emergency alert from users
    POST /api/emergency-alert/
    Body: {"latitude": -13.9626, "longitude": 33.7741, "type": "medical"}
    """
    import json
    
    try:
        data = json.loads(request.body)
        lat = data.get('latitude')
        lon = data.get('longitude')
        alert_type = data.get('type', 'general')
        
        # In production, you would:
        # 1. Save to database
        # 2. Send SMS to emergency contacts
        # 3. Notify nearby responders
        # 4. Log for analytics
        
        logger.info(f"Emergency alert received: {alert_type} at ({lat}, {lon})")
        
        return JsonResponse({
            "success": True,
            "message": "Emergency alert received. Help is on the way.",
            "alert_id": "ALERT-" + str(hash(f"{lat}{lon}"))[:8]
        })
        
    except Exception as e:
        logger.error(f"Error processing emergency alert: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": "Failed to process alert"
        }, status=500)


# urls.py - Add these to your Django URLs
"""
from django.urls import path
from . import views

urlpatterns = [
    path('api/peza/', views.peza_api, name='peza_api'),
    path('api/health/', views.health_check, name='health_check'),
    path('api/emergency-alert/', views.emergency_alert, name='emergency_alert'),
]
"""