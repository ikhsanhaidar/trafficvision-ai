export type VehicleClass = 'car' | 'motorcycle' | 'bus' | 'truck';
export type Point = { x: number; y: number };
export type CountLine = { id: string; start: Point; end: Point };
export type Configuration = {
  classes: VehicleClass[];
  confidence: number;
  image_size: 320 | 480 | 640 | 960 | 1280;
  device: 'cpu' | 'cuda:0';
  roi: Point[];
  lines: CountLine[];
  hysteresis?: number;
  min_track_age?: number;
  max_track_gap?: number;
};
export type VideoInfo = {
  width: number;
  height: number;
  duration_seconds: number;
  fps: number;
  frame_count: number | null;
  codec: string;
  size_bytes: number;
  timing: string;
};
export type Video = {
  id: string;
  filename: string;
  info: VideoInfo;
  created_at: string;
};
export type Direction = 'A_to_B' | 'B_to_A';
export type Summary = {
  crossing_total: number;
  processing_seconds: number;
  throughput_fps: number;
  processed_frames: number;
  video: VideoInfo;
  configuration: Configuration;
  model: Record<string, unknown>;
  counts: {
    class_name: VehicleClass;
    line_id: string;
    direction: Direction;
    count: number;
  }[];
  intervals: {
    start_seconds: number;
    class_name: VehicleClass;
    direction: Direction;
    count: number;
  }[];
  interval_seconds: number;
  notes: string[];
};
export type Job = {
  id: string;
  video_id: string;
  filename: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled';
  configuration: Configuration;
  video: VideoInfo;
  progress: number;
  processing_seconds: number | null;
  throughput_fps: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  attempt: number;
  summary: Summary | null;
  cancel_requested: boolean;
};
export type CrossingEvent = {
  run_id: string;
  track_id: number;
  class_name: VehicleClass;
  line_id: string;
  direction: Direction;
  timestamp_video: number;
};
export type Page<T> = { items: T[]; total: number };
export type Settings = {
  limits: Record<string, number | string>;
  classes: VehicleClass[];
  checkpoint: string;
  devices: string[];
  default_device: 'cpu' | 'cuda:0';
  [key: string]: unknown;
};
export const VEHICLE_CLASSES: VehicleClass[] = [
  'car',
  'motorcycle',
  'bus',
  'truck',
];
