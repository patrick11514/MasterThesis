import EventEmitter from 'eventemitter3';

// prettier-ignore
type AppEvent = 
    // app state
    'Save' | 'Load' |
    // fits import
    'ImportFITS' | 'ImportFITSDirectory' |
    // processing
  'GroupFrames' | 'CalibrateFrames' |
    // command palette
    "OpenCommandPalette"
;

class AppEvents extends EventEmitter<AppEvent> {
  //If existing listeners are present, they will be replaced by the new listener
  public override on<T extends AppEvent>(
    event: T,
    fn: EventEmitter.EventListener<AppEvent, T>,
    context?: never
  ): this {
    super.removeAllListeners(event);
    super.on(event, fn, context);

    return this;
  }
}

export const appEvents = new AppEvents();
