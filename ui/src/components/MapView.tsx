import { useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import { Layers, RefreshCw, Filter } from 'lucide-react';
import { MapLoadingSkeleton } from './LoadingSpinner';
import { getRiskBadgeClass, formatStreamflow, formatTimestamp } from '../lib/api';
import 'leaflet/dist/leaflet.css';
import type { LatLngTuple } from 'leaflet';

interface MapViewProps {
  watersheds?: any[];
  alerts?: any[];
  loading?: boolean;
  refreshData?: () => void;
}

const MapView = ({ watersheds = [], alerts = [], loading = false, refreshData }: MapViewProps) => {
  const [mapLayer, setMapLayer] = useState('terrain');
  const [showAlerts, setShowAlerts] = useState(true);
  const [riskFilter, setRiskFilter] = useState('all');

  // Add fallback data if no watersheds are provided
  const fallbackWatersheds = watersheds.length > 0 ? watersheds : [
    {
      name: "Brahmaputra at Guwahati",
      latitude: 26.1445,
      longitude: 91.7362,
      basin_size_sqmi: 225000,
      current_streamflow_cfs: 706294.0,
      current_risk_level: "High",
      risk_score: 9.1,
      flood_stage_cfs: 848000.0,
      trend: "rising",
      trend_rate_cfs_per_hour: 3500.0,
      last_updated: new Date().toISOString()
    },
    {
      name: "Ganga at Patna",
      latitude: 25.5941,
      longitude: 85.1376,
      basin_size_sqmi: 405400,
      current_streamflow_cfs: 353147.0,
      current_risk_level: "High",
      risk_score: 8.5,
      flood_stage_cfs: 424776.0,
      trend: "rising",
      trend_rate_cfs_per_hour: 1200.0,
      last_updated: new Date().toISOString()
    },
    {
      name: "Mahanadi at Hirakud",
      latitude: 21.5235,
      longitude: 83.8714,
      basin_size_sqmi: 32200,
      current_streamflow_cfs: 141259.0,
      current_risk_level: "High",
      risk_score: 8.2,
      flood_stage_cfs: 170000.0,
      trend: "rising",
      trend_rate_cfs_per_hour: 1100.0,
      last_updated: new Date().toISOString()
    },
    {
      name: "Godavari at Rajahmundry",
      latitude: 17.0005,
      longitude: 81.7799,
      basin_size_sqmi: 120750,
      current_streamflow_cfs: 247103.0,
      current_risk_level: "Moderate",
      risk_score: 6.1,
      flood_stage_cfs: 350000.0,
      trend: "rising",
      trend_rate_cfs_per_hour: 800.0,
      last_updated: new Date().toISOString()
    },
    {
      name: "Yamuna at Delhi",
      latitude: 28.6139,
      longitude: 77.2090,
      basin_size_sqmi: 131900,
      current_streamflow_cfs: 35315.0,
      current_risk_level: "Moderate",
      risk_score: 5.5,
      flood_stage_cfs: 70630.0,
      trend: "rising",
      trend_rate_cfs_per_hour: 450.0,
      last_updated: new Date().toISOString()
    },
    {
      name: "Krishna at Vijayawada",
      latitude: 16.5062,
      longitude: 80.6480,
      basin_size_sqmi: 99980,
      current_streamflow_cfs: 106000.0,
      current_risk_level: "Moderate",
      risk_score: 5.6,
      flood_stage_cfs: 160000.0,
      trend: "stable",
      trend_rate_cfs_per_hour: 30.0,
      last_updated: new Date().toISOString()
    }
  ];

  const fallbackAlerts = alerts.length > 0 ? alerts : [
    {
      alert_id: "fallback-1",
      watershed: "Brahmaputra at Guwahati",
      alert_type: "Flood Warning",
      severity: "High",
      message: "Demo — River level near danger mark. NDMA helpline: 1078",
      issued_time: new Date().toISOString(),
      expires_time: new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString(),
      affected_counties: ["Kamrup", "Goalpara"]
    }
  ];

  // India center coordinates
  const indiaCenter: LatLngTuple = [22.5, 82.0];

  const getRiskColor = (riskLevel: string) => {
    switch (riskLevel?.toLowerCase()) {
      case 'high':
        return '#ef4444';
      case 'moderate':
        return '#f59e0b';
      case 'low':
        return '#22c55e';
      default:
        return '#6b7280';
    }
  };

  const getMarkerSize = (riskScore: number) => {
    return Math.max(8, Math.min(20, (riskScore || 1) * 2));
  };

  const filteredWatersheds = fallbackWatersheds.filter(watershed => {
    if (riskFilter === 'all') return true;
    return watershed.current_risk_level?.toLowerCase() === riskFilter;
  });

  const mapLayers = {
    terrain: {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '© OpenStreetMap contributors'
    },
    satellite: {
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      attribution: '© Esri'
    },
    topo: {
      url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      attribution: '© OpenTopoMap contributors'
    }
  };

  if (loading && watersheds.length === 0) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">India Flood Risk Map</h1>
            <p className="text-gray-600">Interactive river monitoring</p>
          </div>
        </div>
        <MapLoadingSkeleton height={600} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Controls */}
      <div className="flex flex-col lg:flex-row lg:justify-between lg:items-center space-y-4 lg:space-y-0">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            India Flood Risk Map
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            Real-time river conditions and flood alerts across India
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          {/* Risk Filter */}
          <div className="flex items-center space-x-2">
            <Filter className="h-4 w-4 text-gray-500" />
            <select
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              className="text-sm border border-gray-300 rounded-md px-3 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="all">All Risk Levels</option>
              <option value="high">High Risk Only</option>
              <option value="moderate">Moderate Risk Only</option>
              <option value="low">Low Risk Only</option>
            </select>
          </div>

          {/* Map Layer */}
          <div className="flex items-center space-x-2">
            <Layers className="h-4 w-4 text-gray-500" />
            <select
              value={mapLayer}
              onChange={(e) => setMapLayer(e.target.value)}
              className="text-sm border border-gray-300 rounded-md px-3 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="terrain">Terrain</option>
              <option value="satellite">Satellite</option>
              <option value="topo">Topographic</option>
            </select>
          </div>

          {/* Show Alerts Toggle */}
          <label className="flex items-center space-x-2">
            <input
              type="checkbox"
              checked={showAlerts}
              onChange={(e) => setShowAlerts(e.target.checked)}
              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            <span className="text-sm text-gray-700">Show Alerts</span>
          </label>

          {/* Refresh Button */}
          <button 
            className="btn btn-primary"
            onClick={() => {
              if (refreshData) {
                refreshData();
              } else {
                window.location.reload();
              }
            }}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </button>
        </div>
      </div>

      {/* Map Container */}
      <div className="card">
        <div className="h-[600px] w-full">
          <MapContainer
            center={indiaCenter}
            zoom={5}
            style={{ height: '100%', width: '100%' }}
            className="rounded-lg"
          >
            <TileLayer
              url={mapLayers[mapLayer as keyof typeof mapLayers].url}
              attribution={mapLayers[mapLayer as keyof typeof mapLayers].attribution}
            />

            {/* Watershed Markers */}
            {filteredWatersheds.map((watershed) => {
              const lat = watershed.latitude || watershed.location_lat;
              const lng = watershed.longitude || watershed.location_lng;
              
              // Skip watersheds without valid coordinates
              if (!lat || !lng || isNaN(lat) || isNaN(lng)) {
                return null;
              }
              
              return (
              <CircleMarker
                key={watershed.name}
                center={[lat, lng]}
                radius={getMarkerSize(watershed.risk_score)}
                fillColor={getRiskColor(watershed.current_risk_level)}
                color="#ffffff"
                weight={2}
                opacity={1}
                fillOpacity={0.8}
              >
                <Popup>
                  <div className="p-2 min-w-[250px]">
                    <h3 className="font-bold text-lg mb-2">
                      {watershed.name}
                    </h3>
                    
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-600">Risk Level:</span>
                        <span className={`badge ${getRiskBadgeClass(watershed.current_risk_level)}`}>
                          {watershed.current_risk_level}
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-600">Risk Score:</span>
                        <span className="font-medium">
                          {watershed.risk_score}/10
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-600">Current Flow:</span>
                        <span className="font-medium">
                          {formatStreamflow(watershed.current_streamflow_cfs)}
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-600">Flood Stage:</span>
                        <span className="font-medium">
                          {formatStreamflow(watershed.flood_stage_cfs)}
                        </span>
                      </div>
                      
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-600">Basin Size:</span>
                        <span className="font-medium">
                          {watershed.basin_size_sqmi?.toLocaleString()} sq mi
                        </span>
                      </div>

                      {watershed.trend && (
                        <div className="flex justify-between items-center">
                          <span className="text-sm text-gray-600">Trend:</span>
                          <span className={`text-sm font-medium ${
                            watershed.trend === 'rising' ? 'text-danger-600' :
                            watershed.trend === 'falling' ? 'text-success-600' :
                            'text-gray-600'
                          }`}>
                            {watershed.trend}
                            {watershed.trend_rate_cfs_per_hour && 
                              ` (${watershed.trend_rate_cfs_per_hour > 0 ? '+' : ''}${watershed.trend_rate_cfs_per_hour.toFixed(1)} CFS/hr)`
                            }
                          </span>
                        </div>
                      )}
                      
                      <div className="pt-2 border-t border-gray-200">
                        <p className="text-xs text-gray-500">
                          Last updated: {formatTimestamp(watershed.last_updated)}
                        </p>
                      </div>
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
              );
            })}

            {/* Alert Markers */}
            {showAlerts && fallbackAlerts.map((alert) => {
              const watershed = fallbackWatersheds.find(w => w.name === alert.watershed);
              if (!watershed) return null;
              
              const lat = watershed.latitude || watershed.location_lat;
              const lng = watershed.longitude || watershed.location_lng;
              
              // Skip alerts without valid coordinates
              if (!lat || !lng || isNaN(lat) || isNaN(lng)) {
                return null;
              }

              return (
                <CircleMarker
                  key={alert.alert_id}
                  center={[lat + 0.1, lng + 0.1]}
                  radius={8}
                  fillColor={alert.severity === 'High' ? '#dc2626' : '#f59e0b'}
                  color="#ffffff"
                  weight={2}
                  opacity={1}
                  fillOpacity={1}
                >
                  <Popup>
                    <div className="p-2 min-w-[200px]">
                      <h3 className="font-bold text-lg mb-2">
                        🚨 {alert.alert_type}
                      </h3>
                      
                      <div className="space-y-2">
                        <div>
                          <span className={`badge ${
                            alert.severity === 'High' ? 'badge-high' :
                            alert.severity === 'Moderate' ? 'badge-moderate' :
                            'badge-low'
                          }`}>
                            {alert.severity} Severity
                          </span>
                        </div>
                        
                        <p className="text-sm text-gray-700">
                          {alert.message}
                        </p>
                        
                        <div className="text-xs text-gray-600">
                          <p>Watershed: {alert.watershed}</p>
                          <p>Issued: {formatTimestamp(alert.issued_time)}</p>
                          <p>Expires: {formatTimestamp(alert.expires_time)}</p>
                        </div>

                        {alert.affected_counties && alert.affected_counties.length > 0 && (
                          <div className="text-xs text-gray-600">
                            <p>Affected Counties: {alert.affected_counties.join(', ')}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>
        </div>
      </div>

      {/* Legend */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Risk Level Legend */}
        <div className="card">
          <div className="card-header">
            <h3 className="text-lg font-medium text-gray-900">
              Risk Level Legend
            </h3>
          </div>
          <div className="card-body">
            <div className="space-y-3">
              <div className="flex items-center space-x-3">
                <div className="w-4 h-4 rounded-full bg-success-500"></div>
                <span className="text-sm">
                  <strong>Low Risk:</strong> Normal conditions, routine monitoring
                </span>
              </div>
              <div className="flex items-center space-x-3">
                <div className="w-4 h-4 rounded-full bg-warning-500"></div>
                <span className="text-sm">
                  <strong>Moderate Risk:</strong> Elevated conditions, increased caution
                </span>
              </div>
              <div className="flex items-center space-x-3">
                <div className="w-4 h-4 rounded-full bg-danger-500"></div>
                <span className="text-sm">
                  <strong>High Risk:</strong> Dangerous conditions, immediate attention required
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Map Statistics */}
        <div className="card">
          <div className="card-header">
            <h3 className="text-lg font-medium text-gray-900">
              Current Statistics
            </h3>
          </div>
          <div className="card-body">
            <div className="grid grid-cols-2 gap-4">
              <div className="text-center">
                <p className="text-2xl font-bold text-gray-900">
                  {filteredWatersheds.length}
                </p>
                <p className="text-sm text-gray-600">
                  Watersheds Shown
                </p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-danger-600">
                  {showAlerts ? fallbackAlerts.length : 0}
                </p>
                <p className="text-sm text-gray-600">
                  Active Alerts
                </p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-warning-600">
                  {filteredWatersheds.filter(w => w.current_risk_level === 'High').length}
                </p>
                <p className="text-sm text-gray-600">
                  High Risk
                </p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-success-600">
                  {filteredWatersheds.filter(w => w.current_risk_level === 'Low').length}
                </p>
                <p className="text-sm text-gray-600">
                  Low Risk
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MapView;